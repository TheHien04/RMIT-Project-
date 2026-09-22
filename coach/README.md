# Voice coach cho Stage 4

Coach nói tiếng Việt, đứng cạnh người đang thử việc, và chỉ đường tới control trên một cổng nội bộ không có accessibility layer. Người học tự bấm. Coach không bấm hộ trừ khi được nhờ.

Những gì đã chạy và related work (SensePath, NaviNote, Navig-AI-tion) nằm ở `docs/DA_LAM.md`.

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

Sao chép `coach/.env.example` thành `coach/.env` nếu file đó chưa có. `.env` không được commit. `OPENAI_API_KEY` để trống và `COACH_LLM=false` thì câu "không hiểu" trả lời tại máy. `COACH_VISION=false` thì không gửi ảnh control. `COACH_MIC=false` mở sandbox. Trên trang, mũi tên đi qua các `div` bấm được và Enter kích hoạt. Terminal chỉ để hỏi. `COACH_TTS=auto` dùng edge-tts khi gói đó có trong venv, và mỗi câu được ghi là đã rời máy trong `logs/egress.jsonl`.

`demo` chạy vòng kín không TTS mạng: người học giả lập bấm mũi tên và Enter, bảng được lưu.

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

CoreML có trên máy này nhưng graph ZeroTTS lỗi lúc chạy, nên giọng nói dùng CPU. `COACH_BARGE_IN` mặc định tắt vì mic laptop nghe lại loa và sẽ cắt câu nói.

## Chrome thật / Supabase staging

Không đưa credential, MFA, CAPTCHA, token, API key, upload, download, billing
hay trang destructive cho coach. Người học tự đăng nhập trong Chrome profile riêng:

```bash
cd coach
sh scripts/launch_coach_chrome.sh
```

Mở đúng một tab staging đã được phê duyệt, đăng nhập thủ công, rồi đặt `.env`:

```env
COACH_CDP_URL=http://127.0.0.1:9222
COACH_ALLOWED_ORIGINS=https://your-project.supabase.co
COACH_TARGET_TAB_TITLE=Supabase
COACH_TARGET_MANIFEST=fixtures/partner/target-manifest.json
COACH_LESSON_PDF=fixtures/your-supabase-onboarding.pdf
COACH_NAV_MODE=native_focus
COACH_INJECT_NAVIGATION=false
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

Trang có button/link/label đúng chuẩn: để `COACH_NAV_MODE=native_focus`; Tab và
screen reader tự điều hướng. Trang `div` có click listener nhưng không có role:
chỉ bật `COACH_NAV_MODE=coach_list` và `COACH_INJECT_NAVIGATION=true` sau khi
người học nói “đi nút”. Escape hoặc “đọc” trả mũi tên về screen reader. Một
synthetic click chỉ xảy ra sau “bấm giúp” hoặc hoạt hóa rõ ràng trong coach-list,
và được ghi local vào `logs/browser-audit.jsonl`.
