# archive

현행 코드는 아니지만 개발 과정을 보여주는 프로토타입.
`services/exhibition-card` 가 이들을 대체했다.

## solo-call
1:1 영상통화 프로토타입. **Gemini Live Native Audio + Simli WebRTC**.
클라이언트 VAD(임계값 0.02 · 침묵 1초 · preroll 5청크), 24kHz 재생과
16kHz 리샘플을 동시에 흘리는 구조를 여기서 잡았다.
연습생 4인을 dict 에 하드코딩했고, 이 구조가 그대로 카드 DB 로 옮겨갔다.

## multi-call
다자간 통화 프로토타입. 이름은 비슷하지만 **다른 기능**이다.
Gemini 2.5 Flash 로 대사 24줄을 미리 만들고 TTS 를 한 줄 선행 생성해
순차 재생한다. 사람은 듣기만 한다.

전시 카드의 멀티콜은 사람이 실시간으로 끼어들어야 해서 재사용할 수 없었고,
발언권 중재 방식으로 새로 만들었다(`services/exhibition-card/room.py`).
