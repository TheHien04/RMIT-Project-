## Real-web boundary (CDP)

The coach can now attach to a single user-selected Chrome tab over loopback
CDP. The supported deployment path is a dedicated Chrome user-data directory,
manual authentication by the learner, an exact origin allowlist, and a reviewed
target manifest. It does not automate authentication or submit credentials.

For a semantic page, `agent-browser snapshot -i --json` is observation-only
input to the coach; native Tab and the screen reader continue to own navigation.
For a role-less `div` with a click listener, the local CDP detector remains the
fallback. The learner must explicitly enable coach-list mode; Escape returns
arrows to reading mode. Browser attach, denied origin, and explicit assists are
recorded locally in `logs/browser-audit.jsonl`; raw DOM, cookie, token,
password, and screenshot content are excluded from that log and from the LLM.

# Đã làm và related work

Coach là người ngồi cạnh nhân viên thử việc, nói tiếng Việt, chỉ đường tới control trên cổng nội bộ không có lớp accessibility. Người học tự bấm. Coach không bấm hộ trừ khi được nhờ.

## Đã chạy được

Bài mẫu là PDF “tạo bảng ca làm” và sandbox web cố tình không có ARIA (`sandbox/`, `?flow=div`). Control là `div` có `data-coach`, `tabindex=-1`. `?flow=button` chỉ để đối chiếu với nút thật.

Planner đọc PDF thành `LessonPlan`. Mỗi bước giữ câu trích và số trang. Nhãn control phải nằm trong câu trích. Không có selector bịa. Kiểm tra xong bước bằng cờ DOM (`panel`, `columns`, `saved`), không bằng ảnh màn hình.

Buổi học (`session.py`):

- “bắt đầu học” đọc tên module rồi bước hiện tại.
- “tài liệu” đọc lại câu trích và số trang.
- “nhắc lại” đọc lại hướng dẫn bước.
- “tôi bấm rồi” không tự nhảy bước. Trang phải đổi đúng cờ đã ghi trong bài.
- “focus giúp” / “bấm giúp” chỉ chạy sau câu nhờ đó, và vẫn không tính là xong bước.
- Vision tắt mặc định. Ảnh control không rời máy.

Lớp đọc DOM (`dom_map.py`) chạy khi mở trang. Node đang hiện được tính là nút khi là thẻ `button` / `a` / `input`, có `role`, có `onclick`, hoặc CDP `getEventListeners()` thấy `click` / `pointerdown`. Chữ trên node phải trùng nhãn trong câu trích. Một nhãn khớp một node thì `bound`. Hai node cùng chữ thì `ambiguous`, và lựa chọn chỉ được là một trong hai node đó. Không khớp thì `unbound`, coach nói không thấy, không đoán tên.

Người học tự đi. Trang chuẩn accessibility dùng Tab/Shift+Tab và screen reader. Chỉ khi người học nói “đi nút”, coach mới bật danh sách cho trang `div`-only; mũi tên đổi mục, Escape hoặc “đọc” trả mũi tên về screen reader. Coach chỉ đọc tên chỗ họ vừa tới. Đúng nhãn của bước thì nói thêm "Enter." Enter và Space do họ bấm; với `div` không nhận phím, coach-list gọi `click()` như một accommodation đã bật rõ ràng. Coach không đổi mục hộ. "Focus giúp" chỉ khi họ nhờ, và vẫn chờ Enter của họ.

Câu nút, "Enter", "xong bước" và câu trích nói sẵn, không chờ API. Câu hỏi mở, kể cả "không hiểu", gọi OpenAI khi `COACH_LLM=true` và có key. Lỗi mạng thì nói lại câu mặc định. Model chỉ nhận câu bước, nhãn, câu trích và câu người học, không nhận DOM.

Giọng mặc định là Edge TTS (`vi-VN-HoaiMyNeural`). Câu mở bài vẫn gửi Microsoft và ghi `logs/egress.jsonl` với `left_machine=true`. Năm câu hướng được tải nền một lần (`CUE_LINES`). Lần sau phát từ bộ nhớ, `provider=edge-cache`, `left_machine=false`. Playwright đang giữ event loop nên phần tổng hợp Edge chạy trên luồng riêng.

Lệnh, trong `coach/.venv`, không cài lên Python của máy:

```bash
.venv/bin/python -m coach live
.venv/bin/python -m coach demo
.venv/bin/python -m coach serve
```

`live` mở Chromium, người kéo chuột, gõ câu trong terminal. `demo` là vòng kín, không TTS mạng: chuột đi theo câu hướng, bảng được lưu, và không có sự kiện rời máy. `pytest` 28 passed. Hai test bỏ qua vì `zerotts` và `faster_whisper` chưa có trong venv.

## Giới hạn hiện tại

Mic, Silero, Smart Turn, PhoWhisper MLX GPU và ZeroTTS chạy trong `.venv312`. Chrome thật gắn qua CDP loopback có origin allowlist, manual-auth handoff, target manifest và fixture semantic/div-only đã test. Chưa có credential hoặc Supabase staging thật trong repository này: người dùng phải tự đăng nhập một staging tab đã phê duyệt, và không được dùng production account hoặc thao tác destructive.

LLM không nằm trên đường điều hướng, binding hay kiểm tra xong bước. Nó chỉ diễn giải câu hỏi mở với payload tối thiểu.

## Related work

Ba hệ dưới đây dẫn người đi bằng tai. Coach mượn cách nói, không mượn định vị ngoài đời hay model nhìn ảnh.

### SensePath

[SensePath](https://github.com/Ruturaj-Vasant/SensPath) là trợ lý giọng nói cho chặng vài mét cuối: cửa, ghế, thang máy. Ở chế độ đi, nó chỉ nói khi đổi hướng, khi có mốc, hoặc khi tới nơi. Hướng liên tục là beacon âm thanh (Web Audio `StereoPannerNode`), không phải một câu nói lặp lại. Cảnh báo an toàn cắt ngang lời đang đọc.

Coach lấy quy tắc nói: câu hướng chỉ phát khi hướng đổi hoặc khi tới control. Coach không có beacon stereo và không có lớp cảnh báo an toàn. Nhắc lại sau vài giây là từ NaviNote, không phải từ SensePath.

### NaviNote

Chen, Wu và cộng sự, [NaviNote: Enabling In-situ Spatial Annotation Authoring to Support Exploration and Navigation for Blind and Low Vision People](https://doi.org/10.1145/3772318.3790589), CHI 2026. Dẫn đường vài mét cuối cho người mù và nhìn kém, trong vùng đã quét sẵn.

Mục 4.2.3: câu chỉ đường ngắn, ví dụ “2 o’clock, 5 meters”. Câu phát ở chỗ rẽ, mỗi 10 giây để xác nhận nếu vẫn đúng hướng (“Correct direction, 2 meters”), và khi người đi lệch lộ trình. La bàn âm thanh (tiếng beep) chạy liên tục, to khi đúng hướng và nhỏ khi lệch. Lời nói không gánh phần phản hồi tức thì.

Coach lấy hai phần: câu một hơi, và im khi hướng không đổi rồi mới nhắc lại. Khoảng nhắc của coach là 4 giây, câu nhắc là một từ (“Qua phải.”), không có mét, mặt đồng hồ, hay beep.

### Navig-AI-tion

[Navig-AI-tion: Navigation by Contextual AI and Spatial Audio](https://doi.org/10.1145/3772363.3799295), CHI EA 2026. Bản HTML: [arxiv.org/html/2603.13200](https://arxiv.org/html/2603.13200).

Hướng tức thì là tiếng “waterfall” đặt trong không gian (HRTF, Steam Audio), bật khi mặt người lệch quá 25° so với chỗ rẽ và tắt khi đã quay lại trong 25°. TTS chạy trên máy (Android TTS). Model nhìn ảnh (Gemini 2.0 Flash) chỉ tạo câu có mốc, ví dụ “turn left at the fountain”, và chỉ được hỏi ở hai thời điểm: khi người đứng yên rồi nhìn đúng hướng, hoặc khi còn khoảng 30 mét tới chỗ rẽ.

Mục 5.5 ghi độ trễ prompt trung bình khoảng 3,3 giây. Với tốc độ đi bộ khoảng 1,38 m/s, đó là khoảng 4,5 mét. Mốc gần hơn khoảng 5 mét dễ gây rối vì người đã đi qua chỗ model đang mô tả. Nghiên cứu 12 người: thêm cue không gian giảm lệch đường so với chỉ VLM và so với Google Maps đọc chỉ đường. Người tham gia thích mốc và hướng theo người hơn hướng đông tây nam bắc.

Coach lấy kết luận về độ trễ: hướng chuột không chờ model. “Đưa chuột qua phải.” tính từ tâm control và con trỏ. Model không viết câu đó. Coach chưa có âm thanh không gian. TTS Edge vẫn rời máy ở lần đầu của mỗi câu. Các lần sau của câu hướng phát từ cache để không trả lại khoảng chờ mạng.
