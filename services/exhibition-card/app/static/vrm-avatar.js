/**
 * 버추얼 카드 렌더러 (VRM · three-vrm).
 *
 * Simli가 서버에서 립싱크 영상을 만들어 보내는 것과 달리, 여기서는 브라우저가
 * 모델을 직접 그리고 재생 중인 응답 오디오의 음량으로 입을 움직인다.
 *   Gemini Live 응답 → AnalyserNode → RMS → 'aa' 표정값
 * 등록 대기가 없어서 카드 발급 즉시 영상통화가 된다.
 *
 * three · three-vrm은 scan.html의 importmap으로 불러온다.
 */
window.AidolVRM = (() => {
  let libs = null;
  async function load() {
    if (!libs) {
      libs = Promise.all([
        import('three'),
        import('three/addons/loaders/GLTFLoader.js'),
        import('@pixiv/three-vrm'),
      ]).then(([THREE, { GLTFLoader }, VRM]) => ({ THREE, GLTFLoader, ...VRM }));
    }
    return libs;
  }

  // 꾸미기에서 색을 바꿀 수 있는 부위. VRoid가 내보내는 재질 이름 규칙을 따른다.
  const PARTS = {
    hair:   /HAIR/i,
    eye:    /EyeIris/i,
    top:    /Tops/i,
    bottom: /Bottoms/i,
    shoes:  /Shoes/i,
  };

  /**
   * 텍스처를 한 색으로 다시 칠한다.
   * 픽셀 밝기를 텍스처 평균 밝기로 나눈 비율만큼 목표색을 곱해서, 원래 음영과
   * 하이라이트는 남기고 평균 색만 목표색이 되게 한다. 원래 색이 무엇이든 같은 결과가 난다.
   */
  function recolorTexture(THREE, src, hex) {
    const img = src.image;
    const scale = Math.min(1, 1024 / Math.max(img.width, img.height));
    const w = Math.round(img.width * scale), h = Math.round(img.height * scale);
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h);
    const px = data.data;

    let sum = 0, n = 0;
    for (let i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 8) continue;
      sum += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
      n++;
    }
    const mean = n ? sum / n : 128;
    const tr = parseInt(hex.slice(1, 3), 16), tg = parseInt(hex.slice(3, 5), 16),
          tb = parseInt(hex.slice(5, 7), 16);
    for (let i = 0; i < px.length; i += 4) {
      const k = (0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]) / mean;
      px[i] = tr * k; px[i + 1] = tg * k; px[i + 2] = tb * k;   // Uint8Clamped라 255에서 잘린다
    }
    ctx.putImageData(data, 0, 0);

    const tex = new THREE.CanvasTexture(cv);
    tex.flipY = src.flipY;
    tex.colorSpace = src.colorSpace;
    tex.wrapS = src.wrapS; tex.wrapT = src.wrapT;
    return tex;
  }

  /**
   * container 안에 캔버스를 만들어 모델을 띄운다.
   * analyser: 응답 오디오가 지나가는 AnalyserNode (입 움직임의 원천).
   *   멀티콜처럼 화자가 바뀌는 경우엔 매 프레임 불리는 함수로 넘긴다 — 이 캐릭터가
   *   말할 차례면 AnalyserNode, 아니면 null.
   * opts.colors: 부위별 색 { hair: '#rrggbb', ... } — 꾸미기 결과
   * 돌려주는 객체의 dispose()로 정리하고, recolor()로 색을 다시 입힌다.
   */
  async function mount(container, url, analyser, opts = {}) {
    const { THREE, GLTFLoader, VRMLoaderPlugin, VRMUtils } = await load();

    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:1;display:block';
    container.prepend(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 20);
    const light = new THREE.DirectionalLight(0xffffff, Math.PI);
    light.position.set(0.5, 1.5, 2);
    scene.add(light, new THREE.AmbientLight(0xffffff, 0.6));

    const loader = new GLTFLoader();
    loader.register((p) => new VRMLoaderPlugin(p));
    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm;
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.rotateVRM0(vrm);   // VRM 0.x는 뒤를 보고 있으므로 돌려세운다
    scene.add(vrm.scene);

    // 부위별 재질을 모아둔다. 원래 텍스처는 되돌릴 때를 위해 보관한다.
    const byPart = {};
    vrm.scene.traverse((o) => {
      if (!o.isMesh) return;
      for (const m of [].concat(o.material)) {
        const part = Object.keys(PARTS).find((k) => PARTS[k].test(m.name || ''));
        if (!part || !m.map) continue;
        m.userData.origMap ??= m.map;
        (byPart[part] ??= new Set()).add(m);
      }
    });
    const made = [];   // 만든 텍스처 — dispose 때 치운다
    function recolor(colors = {}) {
      const cache = new Map();   // 같은 원본 텍스처는 한 번만 칠한다
      for (const [part, mats] of Object.entries(byPart)) {
        const hex = colors[part];
        for (const m of mats) {
          const orig = m.userData.origMap;
          let tex = orig;
          if (hex) {
            const key = orig.uuid + hex;
            if (!cache.has(key)) { cache.set(key, recolorTexture(THREE, orig, hex)); made.push(cache.get(key)); }
            tex = cache.get(key);
          }
          if (m.shadeMultiplyTexture === m.map) m.shadeMultiplyTexture = tex;
          m.map = tex;
        }
      }
    }
    if (opts.colors) recolor(opts.colors);

    // T포즈 팔을 내리고, 얼굴~가슴이 화면에 차도록 카메라를 맞춘다
    const bone = (n) => vrm.humanoid.getNormalizedBoneNode(n);
    if (bone('leftUpperArm')) bone('leftUpperArm').rotation.z = -1.2;
    if (bone('rightUpperArm')) bone('rightUpperArm').rotation.z = 1.2;
    if (bone('leftLowerArm')) bone('leftLowerArm').rotation.z = -0.15;
    if (bone('rightLowerArm')) bone('rightLowerArm').rotation.z = 0.15;
    vrm.update(0);
    const head = new THREE.Vector3();
    (bone('head') || vrm.scene).getWorldPosition(head);
    const target = new THREE.Vector3(0, head.y - 0.08, 0);
    camera.position.set(0, head.y - 0.02, 1.35);
    camera.lookAt(target);

    function resize() {
      const w = container.clientWidth || 1, h = container.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // 세로로 긴 화면에서도 얼굴이 잘리지 않도록 좁은 쪽 기준으로 화각을 넓힌다
      camera.fov = w < h ? 24 * Math.min(h / w, 1.8) : 24;
      camera.updateProjectionMatrix();
    }
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    resize();

    // 입: 음량을 표정값으로. 바로 대입하면 떨리므로 부드럽게 따라가게 한다
    let buf = null, mouth = 0;
    function level() {
      const a = typeof analyser === 'function' ? analyser() : analyser;
      if (!a) return 0;
      if (!buf || buf.length !== a.fftSize) buf = new Float32Array(a.fftSize);
      a.getFloatTimeDomainData(buf);
      let s = 0;
      for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
      return Math.min(1, Math.sqrt(s / buf.length) * 6);
    }

    // 눈: 3~6초마다 150ms 깜빡임
    let nextBlink = 2, blinkT = -1;

    const clock = new THREE.Clock();
    let raf = 0, alive = true;
    function tick() {
      if (!alive) return;
      raf = requestAnimationFrame(tick);
      const dt = clock.getDelta(), t = clock.elapsedTime;
      const em = vrm.expressionManager;

      const v = level();
      mouth += (v - mouth) * (v > mouth ? 0.5 : 0.2);
      if (em) em.setValue('aa', mouth < 0.05 ? 0 : mouth);

      if (blinkT < 0 && t > nextBlink) blinkT = 0;
      if (blinkT >= 0) {
        blinkT += dt;
        const b = blinkT < 0.075 ? blinkT / 0.075 : Math.max(0, 1 - (blinkT - 0.075) / 0.075);
        if (em) em.setValue('blink', b);
        if (blinkT > 0.15) { blinkT = -1; nextBlink = t + 3 + Math.random() * 3; }
      }

      // 가만히 서 있으면 인형 같아서 숨쉬기와 고개 흔들림을 조금 준다
      if (bone('spine')) bone('spine').rotation.x = Math.sin(t * 1.4) * 0.015;
      if (bone('neck')) {
        bone('neck').rotation.y = Math.sin(t * 0.5) * 0.06;
        bone('neck').rotation.x = Math.sin(t * 0.7) * 0.03 + mouth * 0.04;
      }

      vrm.update(dt);
      renderer.render(scene, camera);
    }
    tick();

    /**
     * 지금 모습을 카드 비율 JPEG로 찍는다. 깜빡임 · 입 모양은 풀고 찍는다.
     * (VRoid의 happy는 눈을 감기므로 쓰지 않는다)
     * 보이는 캔버스 크기를 잠깐 바꿨다가 바로 되돌린다.
     */
    function snapshot(w = 630, h = 700) {
      const em = vrm.expressionManager;
      if (em) { em.setValue('blink', 0); em.setValue('aa', 0); }
      vrm.update(0);
      renderer.setPixelRatio(1);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.fov = 24 * Math.min(h / w, 1.8);
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);

      const out = document.createElement('canvas');
      out.width = w; out.height = h;
      const ctx = out.getContext('2d');
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, '#e3f1ff'); g.addColorStop(1, '#f7e6f1');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(renderer.domElement, 0, 0);   // 렌더 직후라 버퍼가 아직 남아 있다

      renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      resize();
      return new Promise((res) => out.toBlob(res, 'image/jpeg', 0.88));
    }

    function dispose() {
      alive = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      made.forEach((t) => t.dispose());
      VRMUtils.deepDispose(vrm.scene);
      renderer.dispose();
      canvas.remove();
    }
    return { dispose, canvas, recolor, snapshot, parts: Object.keys(byPart) };
  }

  return { mount };
})();
