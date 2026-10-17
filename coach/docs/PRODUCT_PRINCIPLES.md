# Nguyên tắc sản phẩm

Companion navigator cần tách rõ hai thứ:

1. Khả năng truy cập giúp người dùng thao tác được.
2. Lời hướng dẫn giúp người dùng học cách sử dụng công nghệ.

Companion navigator nên tồn tại suốt vòng đời. Nhưng phần “coach nói và nhắc” phải giảm dần; phần “bảo đảm website vẫn thao tác được” thì không được giảm.

## Độc lập không có nghĩa là không dùng công cụ hỗ trợ

Người khiếm thị sử dụng screen reader vẫn được xem là độc lập. Tương tự, nếu companion navigator giúp biến một `div` không thể Tab thành một control dùng bàn phím được, người dùng vẫn độc lập vì họ:

- Tự quyết định mục tiêu.
- Tự di chuyển.
- Tự nhấn Enter.
- Tự xử lý lỗi.
- Không phụ thuộc vào người sáng mắt.

W3C cũng xem những cơ chế điều hướng bổ sung và biến đổi nội dung để dễ tiếp cận là chức năng hợp lệ của assistive technology. [W3C definition of assistive technology](https://www.w3.org/WAI/WCAG22/Understanding/page-titled.html).

Vì vậy, navigator không nhất thiết phải biến mất. Thứ cần biến mất dần là lời nhắc dư thừa.

## Hai lớp phải có vòng đời khác nhau

```text
Accessibility Runtime
├── Luôn sẵn sàng
├── Sửa rào cản keyboard
├── Cung cấp navigator khi cần
└── Không giảm theo trình độ

Learning Coach
├── Hướng dẫn chi tiết lúc mới học
├── Giảm lời thoại khi người dùng tiến bộ
├── Chờ người dùng yêu cầu
└── Có thể gần như im lặng
```

Ví dụ `Create a table`:

- Người dùng mới: navigator sửa khả năng truy cập và coach giải thích cách tìm.
- Người dùng đã quen: navigator vẫn sửa control, nhưng coach không giải thích nữa.
- Người dùng thành thạo: họ Tab tới “Create a table” và nhấn Enter như một control bình thường; coach im lặng.
- Khi Supabase thay đổi UI hoặc người dùng mắc kẹt: coach xuất hiện trở lại.

Đây là “fading instruction”, không phải “fading accessibility”.

## Rủi ro nếu navigator làm quá nhiều

Nếu companion navigator luôn đọc từng bước và luôn đưa người dùng tới target, sản phẩm có thể tạo ra ba vấn đề.

### Học navigator thay vì học website

Người dùng có thể biết:

> “Mở coach, nhấn xuống ba lần.”

Nhưng không hình thành được mô hình:

> “Table Editor nằm trong thanh điều hướng project; Create a table nằm ở vùng nội dung chính.”

Khi không có coach, kiến thức không chuyển giao được.

### Nhầm lẫn giữa thành thạo và được làm hộ

Một người hoàn thành nhanh vì coach tự focus/click không có nghĩa họ đã học được quy trình.

Vì vậy metric chính không nên chỉ là “task completed”. Cần đo “task completed với mức hỗ trợ nào”.

### Giảm hỗ trợ quá sớm

Không nên giảm lời hướng dẫn chỉ vì người dùng đã sử dụng app nhiều ngày. Nghiên cứu về scaffolding cho thấy việc giảm hỗ trợ cần thích ứng; fading không phải lúc nào cũng tốt hơn duy trì hỗ trợ. [Study on sustained versus faded scaffolding](https://www.sciencedirect.com/science/article/pii/S0747563218300414).

## Vòng đời trải nghiệm nên như sau

### Giai đoạn 1: Orientation

Mục tiêu: xây dựng mô hình tinh thần của website.

Coach nói:

> “Supabase project có thanh điều hướng bên trái và vùng nội dung chính. Table Editor dùng để quản lý bảng.”

Ở giai đoạn này nên giải thích:

- Trang được chia thành vùng nào.
- Control có vai trò gì.
- Tại sao cần mở nó.
- Phím nào dùng để thao tác.
- Dấu hiệu nào cho biết đã thành công.

Không nên chỉ đọc “Tab, Tab, Enter”.

### Giai đoạn 2: Guided practice

Coach đưa mục tiêu và gợi ý vừa đủ:

> “Hãy mở Table Editor. Nó nằm trong thanh điều hướng project.”

Sau đó chờ người dùng tự làm.

Chỉ khi người dùng mắc kẹt mới nâng mức gợi ý:

> “Bạn đang ở SQL Editor. Table Editor nằm trước mục này.”

### Giai đoạn 3: Independent practice

Coach chỉ nói mục tiêu:

> “Hãy tạo một bảng mới.”

Không tự nói vị trí hay phím.

Nếu người dùng làm đúng, chỉ xác nhận ngắn:

> “Đã mở trình tạo bảng.”

### Giai đoạn 4: Silent companion

Navigator vẫn chạy để:

- Sửa target không nhận bàn phím.
- Phát hiện route thay đổi.
- Bảo vệ thao tác nhạy cảm.
- Trả lời khi được hỏi.

Nhưng coach không tự đọc bước.

Người dùng có thể hỏi:

- “Tôi đang ở đâu?”
- “Mục này làm gì?”
- “Tôi cần đi đâu?”
- “Cho tôi một gợi ý.”
- “Đọc lại bước.”
- “Tôi không tới được.”

### Giai đoạn 5: Recovery

Khi website đổi giao diện, target biến mất hoặc người dùng mắc kẹt, coach tăng hỗ trợ trở lại cho riêng kỹ năng đó.

Không reset toàn bộ người dùng về chế độ mới học.

## Dùng hint ladder thay vì nói đáp án ngay

Khi người dùng cần hỗ trợ, coach tăng dần:

1. Không nói gì, cho người dùng thời gian thử.
2. Nhắc mục tiêu: “Bạn cần tìm Create a table.”
3. Nhắc vùng: “Nó nằm trong vùng nội dung chính.”
4. Nhắc loại control: “Đó là một nút tạo bảng.”
5. Nhắc thao tác: “Tiếp tục Tab; khi nghe Create a table thì Enter.”
6. Accessibility repair hoặc mở navigator.
7. Focus assist nếu người dùng yêu cầu.
8. Click chỉ khi người dùng nói rõ “bấm giúp”.

Mỗi lần chỉ cung cấp một mức, không đọc toàn bộ đáp án.

## Không nên có một mức “thành thạo” toàn cục

Người dùng có thể:

- Thành thạo Table Editor.
- Chưa biết SQL Editor.
- Biết Supabase nhưng chưa biết dialog tạo bảng.
- Đã quen phiên bản cũ nhưng chưa quen UI mới.

Do đó mastery cần lưu theo kỹ năng:

```text
Supabase
├── Điều hướng project sidebar
├── Mở Table Editor
├── Tạo bảng
├── Thêm cột
├── Hiểu primary key
└── Lưu bảng
```

Mỗi kỹ năng có thể có:

```text
attempts
successful_without_hint
highest_hint_level
time_to_complete
focus_loops
help_requests
last_success
page_version
```

Chỉ giảm hướng dẫn khi người dùng đã hoàn thành cùng kỹ năng vài lần mà không cần hint. Khi UI thay đổi, giảm confidence của kỹ năng liên quan, không xóa toàn bộ tiến độ.

## Người dùng phải kiểm soát mức hỗ trợ

Coach có thể đề xuất:

> “Bạn đã hoàn thành bước này ba lần mà không cần gợi ý. Lần sau tôi chỉ nói khi bạn hỏi, được không?”

Người dùng phải có các lệnh:

- “Nói ít hơn.”
- “Hướng dẫn chi tiết.”
- “Chỉ báo khi tôi sai.”
- “Đừng tự nhắc.”
- “Luôn mô tả trang mới.”
- “Quay lại chế độ học.”

Không nên để thuật toán âm thầm quyết định rằng người dùng “đã giỏi”.

## Companion navigator nên hoạt động thế nào

Nó nên là hạ tầng ổn định giống screen reader, không phải một bài hướng dẫn tạm thời:

```text
PageScene
   ↓
Accessibility Adapter
   ├── Native focus
   ├── Target keyboard repair
   └── Accessible navigator fallback
   ↓
Learning Coach
   ├── Guided
   ├── Practice
   ├── On-demand
   └── Silent
```

Navigator chỉ xuất hiện khi trang có rào cản. Trên trang accessible, nó nằm im và để người dùng dùng screen reader/Tab bình thường.

Nghiên cứu đồng thiết kế công cụ điều hướng với người dùng screen reader cũng nhấn mạnh việc cho phép người dùng thay đổi mức chi tiết và cách khám phá thông tin, thay vì áp đặt một luồng duy nhất. [Co-designed navigation system for visually impaired screen-reader users](https://pubmed.ncbi.nlm.nih.gov/40478980/).

## Kết luận phản biện

Ý tưởng “companion đi cùng người dùng suốt vòng đời” là đúng nếu companion trở thành assistive technology đáng tin cậy.

Nó sẽ thất bại nếu trở thành một người hướng dẫn luôn nói đáp án.

Nguyên tắc sản phẩm nên là:

> Accessibility support stays. Instruction fades. User agency grows.

Với `Create a table`, keyboard repair hoặc navigator có thể luôn tồn tại vì lỗi nằm ở website. Nhưng lần đầu coach giải thích đầy đủ; các lần sau chỉ nói “Nút Create a table”; khi người dùng thành thạo thì hoàn toàn im lặng và chỉ phản hồi khi được hỏi.
