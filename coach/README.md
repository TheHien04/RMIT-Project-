# Voice coach cho Stage 4

Coach nói tiếng Việt, đứng cạnh người đang thử việc, và chỉ đường tới control trên một cổng nội bộ không có accessibility layer. Người học tự bấm. Coach không bấm hộ trừ khi được nhờ.

Tài liệu kiến trúc, UX, kiểm thử và trạng thái triển khai được lập chỉ mục tại
[`docs/README.md`](docs/README.md).

Cài đặt nằm trong `coach/.venv`. Không cài gói lên Python của máy.

```bash
cd coach
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pip install edge-tts
.venv/bin/python -m pytest
.venv/bin/python -m coach live
```

Sao chép `coach/.env.example` thành `coach/.env` nếu file đó chưa có, rồi chạy `chmod 600 coach/.env`. `.env` không được commit. `OPENAI_API_KEY` để trống và `COACH_LLM=false` thì câu "không hiểu" trả lời tại máy. Khi bật cloud LLM, Coach phải xin đồng ý bằng giọng nói trong từng session trước khi gửi câu hỏi và nội dung bước; audio, DOM, mật khẩu và ảnh không nằm trong payload này. `COACH_VISION=false` thì không gửi ảnh control. Khi bật, Vision có consent riêng; ảnh được che input/vùng nhạy cảm, chỉ giữ trong RAM cho một request và không ghi xuống đĩa. `COACH_MIC=false` mở sandbox. Trên trang, mũi tên đi qua các `div` bấm được và Enter kích hoạt. Terminal chỉ để hỏi. `COACH_TTS=auto` dùng edge-tts khi gói đó có trong venv, và mỗi câu được ghi là đã rời máy trong `logs/egress.jsonl`.

`demo` chạy vòng kín không TTS mạng: người học giả lập bấm mũi tên và Enter, bảng được lưu.

## Mở bằng ứng dụng, không cần Terminal

Sau khi đã cài `.venv312` một lần, chạy `sh scripts/build_macos_app.sh`, rồi mở
`Coach Companion.app` bằng cách double-click trong Finder. Bundle này là build
output cục bộ và không được commit. Ứng dụng tự mở bảng điều khiển local tại
`http://127.0.0.1:8787`; chọn **Bật Voice Coach** để khởi động micro và toàn bộ
voice pipeline. Chọn **Dừng Voice Coach** để giải phóng micro mà không đánh dấu
bài học hoàn thành.

Nếu Chrome riêng của Coach chưa mở, giao diện sẽ hiện **Mở Chrome Supabase**.
Nút này mở thẳng `COACH_START_URL` trong profile riêng; mặc định là Supabase
Dashboard. Người dùng đăng nhập thủ công, mở project cần học, quay lại app và chọn
**Bật Voice Coach**. App không đưa nội dung `.env`, transcript hay DOM ra frontend.

Build local bằng `sh scripts/build_macos_app.sh`; script tạo bundle từ
`app_launcher/`, seal toàn bộ bundle và verify chữ ký. Bản phân phối cần đặt
`COACH_CODESIGN_IDENTITY` thành Developer ID,
sau đó notarize bằng tài khoản Apple trước khi gửi cho người dùng khác.

Nhà phát triển vẫn có thể mở cùng giao diện bằng lệnh:

```bash
cd coach
.venv312/bin/python -m coach app
```

`serve` mở `http://127.0.0.1:8765/?flow=div`. Kịch bản nằm ở `demo/SCRIPT.md`.

Voice agent (Silero, Smart Turn, PhoWhisper, ZeroTTS) chạy trong `coach/.venv312` với Python 3.12. `zerotts` 0.1.1 không khớp model ONNX hiện tại và onnxruntime trên Python 3.9 không chạy được graph đó.

```bash
# từ thư mục coach, sau khi đã có uv
uv venv .venv312 --python 3.12
uv pip install --python .venv312/bin/python -e ".[dev,voice]"
.venv312/bin/python -m coach speak
COACH_MIC=true .venv312/bin/python -m coach live
```

`speak` tải ZeroTTS local và phát một câu ra loa. `COACH_MIC=true` mở browser sandbox cùng mic: Silero, Smart Turn, PhoWhisper trên GPU (MLX), câu hỏi mở qua OpenAI, rồi ZeroTTS stream từng khúc. Hãy nói “bắt đầu học”; coach mới đọc bước đầu. Browser dùng DOM để nhận các `div` có click listener, đối chiếu đúng tên với PDF, rồi nói control người dùng đi tới bằng mũi tên. User tự Enter để kích hoạt. “focus giúp” và “bấm giúp” là hai lệnh assist riêng.

Ba layer lúc chạy mic:

- Layer 1: PDF → `LessonPlan`, mỗi bước có trích dẫn và điều kiện DOM hoàn thành.
- Layer 1.5: `BrowserLessonBridge` đọc clickable DOM bằng native tag, role, inline handler hoặc CDP listener; chỉ bind nhãn trùng chính xác với PDF.
- Layer 2: VAD → Smart Turn → ASR → `LearningSession`; câu hỏi mở gửi payload tối thiểu tới LLM, còn tên control, hướng và trạng thái bước là local. DOM cập nhật lại bước chỉ khi trang đổi.

Coach dùng speech policy `quiet`: không đọc mọi control khi focus đi qua. Nó chỉ
tự nói bước mới, đúng target, completion và cảnh báo. “Cái này là gì” đọc mô tả
control hiện tại; “tôi cần đi đâu” nhắc target; “mô tả trang” bắt đầu flow
vision. Nếu target unbound/ambiguous qua hai snapshot ổn định, coach có thể đề
nghị dùng ảnh. Vision chỉ mô tả, không được chọn selector, click hay hoàn thành
bước.

## Companion học cùng người dùng

Accessibility runtime và Learning Coach là hai lớp độc lập. Khả năng dùng bàn
phím không bị tắt khi người học đã quen; chỉ lượng lời hướng dẫn giảm dần theo
từng kỹ năng: `orientation` → `guided` → `practice` → `on_demand`. Nếu focus đi
vòng, coach tạm vào recovery và nhắc lại mục tiêu. Tiến độ tối thiểu được lưu ở
`state/progress.json`; file này không chứa transcript, DOM, URL hay ảnh.
Coach chỉ đề xuất mức ít lời hơn ở lần luyện kế tiếp và chờ người dùng nói
“đồng ý” hoặc “giữ nguyên”; thuật toán không âm thầm hạ hỗ trợ.

Các lệnh giọng nói: “gợi ý”, “nói ít hơn”, “hướng dẫn chi tiết”, “chỉ báo khi
tôi sai”, “đừng tự nhắc”, “quay lại chế độ học”, và “mở danh sách điều khiển”.
Thang gợi ý đi từ tên mục tiêu, vùng, vai trò/chức năng, cách dùng Tab, rồi mới
đề nghị navigator hoặc `focus giúp`.

Ba ý định kết thúc được tách riêng để tránh dừng nhầm thành hoàn thành:

- “Dừng hướng dẫn”: kết thúc voice session, giữ bước hiện tại ở trạng thái chưa hoàn thành.
- “Xong bước này”: coach kiểm tra điều kiện DOM rồi mới sang bước kế tiếp. Nếu
  DOM không xác minh được, coach yêu cầu nói chính xác “tôi xác nhận xong bước này”.
- “Tôi đã hoàn thành bài học”: coach kiểm tra điều kiện hoàn tất toàn bài. Nếu
  không xác minh được, coach yêu cầu nói chính xác “tôi xác nhận hoàn thành bài học”.

Tiến độ lưu cả nguồn `dom_verified` hoặc `user_confirmed`. Chỉ kết quả được DOM
xác minh mới được tính là một lần hoàn thành độc lập để tự động giảm lời hướng dẫn.

## Thiết kế học tập

Manifest có thể khai báo khối `learning` gồm mục tiêu, cấp Bloom, tình huống
thực tế, phần tổng kết khái niệm, câu hỏi nhìn lại, bài tự luyện chuyển giao và
các bằng chứng thành công. Metadata này chỉ tạo lời hướng dẫn; nó không cấp
quyền browser, không tạo selector và không thể đánh dấu hoàn thành một bước.

Luồng Supabase hiện dùng cách tổ chức Active–Applied–Authentic kết hợp chu trình
trải nghiệm: người học tự làm nhiệm vụ thật, nghe một tóm tắt ngắn sau khi hoàn
thành, nhìn lại chiến lược vừa dùng và có thể nói “bài tự luyện” để nhận nhiệm
vụ tương tự trong bối cảnh mới. Có thể nói “mục tiêu bài học”, “bài này để làm
gì”, “nhìn lại bài học” hoặc “bài tự luyện” bất kỳ lúc nào trong phiên.

Progress chỉ ghi số lần câu hỏi nhìn lại và bài tự luyện được đưa ra, không ghi
câu trả lời, transcript hay nội dung DOM. Mức hỗ trợ chỉ giảm theo chuỗi hoàn
thành độc lập liên tiếp; một lần dùng gợi ý, đi vòng focus hoặc tự xác nhận khi
DOM chưa kiểm chứng sẽ đặt lại chuỗi này.

`COACH_KEYBOARD_REPAIR=target_only` chỉ sửa đúng control được lesson và manifest
phê duyệt, chỉ khi nó là `div` có click handler nhưng không nhận bàn phím. Runtime
thêm `role`, `tabindex` và handler Enter/Space trong DOM đang chạy; không sửa mã
nguồn website, không tự focus và không tự click. Manifest cũng phải đặt
`accessibility.keyboard_repair_allowed=true`. Mọi lần sửa được audit cục bộ.

Các mốc `vad_stop`, `asr_final`, `agent_first_token`, `tts_first_pcm` và
`audio_started` được ghi dạng duration vào `logs/latency.jsonl`, không kèm
transcript hoặc nội dung trang.

Sau một warm run, kiểm tra từng SLO bằng log thật (mặc định yêu cầu 100 mẫu):

```bash
.venv312/bin/python -m coach latency-report --kind voice
.venv312/bin/python -m coach latency-report --kind browser
.venv312/bin/python -m coach latency-report --kind vision
```

CoreML có trên máy này nhưng graph ZeroTTS lỗi lúc chạy, nên giọng nói dùng CPU. `COACH_BARGE_IN` mặc định tắt vì mic laptop nghe lại loa và sẽ cắt câu nói.

## Chrome thật / Supabase staging

Không đưa credential, MFA, CAPTCHA, token, API key, upload, download, billing
hay trang destructive cho coach. Người học tự đăng nhập trong Chrome profile riêng.
Cách khuyến nghị là dùng nút **Mở Chrome Supabase** trong Coach Companion: app
tự chọn cổng CDP ngẫu nhiên, truyền riêng cho voice process và đóng Chrome cùng app.

Nếu cần chạy thủ công để phát triển, chọn một cổng riêng và dùng đúng cổng đó
trong `.env`:

```bash
cd coach
COACH_CDP_PORT=49173 sh scripts/launch_coach_chrome.sh
```

Mở đúng một tab staging đã được phê duyệt, đăng nhập thủ công, rồi đặt `.env`:

```env
COACH_CDP_URL=http://127.0.0.1:49173
COACH_ALLOWED_ORIGINS=https://your-project.supabase.co
COACH_TARGET_TAB_TITLE=Supabase
COACH_TARGET_MANIFEST=fixtures/web/partner/target-manifest.json
COACH_LESSON_PDF=fixtures/lessons/your-supabase-onboarding.pdf
COACH_NAV_MODE=native_focus
COACH_INJECT_NAVIGATION=false
COACH_ASSISTANCE_LEVEL=adaptive
COACH_KEYBOARD_REPAIR=target_only
```

Cài adapter accessibility cục bộ một lần rồi trỏ cấu hình tới nó:

```bash
npm install --prefix .tools agent-browser
```

```env
COACH_AGENT_BROWSER_BIN=.tools/node_modules/.bin/agent-browser
```

Sau đó chạy `.venv312/bin/python -m coach live`. Coach chỉ attach đúng tab/origin
được duyệt. Nếu tab chuyển sang origin khác, coach dừng hướng dẫn. `agent-browser`
được gọi ở chế độ snapshot accessibility chỉ-đọc khi `COACH_AGENT_BROWSER_BIN`
trỏ tới binary; control không có accessibility layer dùng local CDP fallback.

Luồng acceptance Supabase có bốn bước đã review: `Table Editor` →
`Create a table` → nhập `coach_demo_tasks` vào `Name` → `Save`. Người học tự
dùng Tab, nhập dữ liệu và nhấn Enter. `Save` ghi schema thật vào project staging,
vì vậy coach từ chối synthetic click cho bước này dù người dùng nói “bấm giúp”.
Bài chỉ hoàn thành sau khi Supabase điều hướng tới route của bảng vừa tạo. Chạy bằng:

```bash
cd coach
COACH_CDP_PORT=49173 sh scripts/launch_coach_chrome.sh
# đăng nhập staging và mở đúng một tab project đã duyệt
.venv312/bin/python -m coach live
```

CDP có toàn quyền trên profile Chrome trong lúc chạy. Chỉ dùng profile staging
riêng, không mở trang cá nhân/production và đóng Chrome ngay sau phiên học.

Sau lời chào, nói “bắt đầu học”. Có thể nói “gợi ý”, “tôi đang ở đâu” hoặc
“hướng dẫn chi tiết”; không cần tự chuyển navigation mode.

Giữ `COACH_NAV_MODE=native_focus` làm mặc định để Tab và screen reader hoạt động
theo chuẩn của trang. Với target `div` bị thiếu keyboard semantics, dùng
`COACH_KEYBOARD_REPAIR=target_only`; người học vẫn tự Tab và Enter.
`COACH_SPEECH_POLICY=focus` khi người học cần coach đọc tên từng control nhận
focus. Khi đã dùng screen reader riêng, có thể đặt `quiet` để tránh hai giọng
đọc chồng nhau. Ở chế độ `focus`, target được đọc rõ “Đã tới … Nhấn Enter”, và
focus mới sẽ hủy lời đọc focus cũ để giọng nói không tụt lại phía sau thao tác.
Chỉ bật `COACH_INJECT_NAVIGATION=true` như fallback rồi để người học nói “mở danh sách
điều khiển”. Escape hoặc “đọc” trả mũi tên về screen reader. Synthetic click chỉ
xảy ra sau “bấm giúp” hoặc hoạt hóa rõ ràng trong danh sách, và được ghi local
vào `logs/browser-audit.jsonl`.
