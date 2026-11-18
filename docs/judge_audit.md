# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay, verdict lưu sẵn trong CSV, không cần key). FAIL là lớp dương: việc của judge là **tìm** reply lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (lệnh exit 0) | **dùng**, chỉ cho tone; không chặn release một mình |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (lệnh exit 1) | **loại** |

Ma trận nhầm lẫn:

| | tp | fp | fn | tn | Tỉ lệ fail quan sát → hiệu chỉnh Rogan-Gladen |
|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 → 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 → 0.30 |

## ≥5 case audit thủ công (tone_ok, 10 bất đồng)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Judge coi xưng "em/nha" là thân thiện. Rubric thêm: *xưng hô với khách dùng "anh/chị", "LogiX"; không "em", "bạn", "nha"*. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ… rồi nha." | PASS | FAIL | Người | Cùng lỗi xưng hô; thêm 1 ví dụ FAIL có "bạn ơi" vào few-shot. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bị "Dạ, vui lòng" đánh lừa. Rubric: *câu mệnh lệnh / chặn khách liên hệ ("không cần nhắn thêm") là FAIL dù có kính ngữ*. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: *xin lỗi không bắt buộc; ngắn mà đủ ý và lịch sự là PASS*. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Style guide CS LogiX cho phép từ "refund". Rubric ghi danh sách thuật ngữ tiếng Anh được phép. |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải tone → không giao cho judge tone; thêm vào phạm vi grader code (so reply với ledger/status). |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric: *không emoji trong phản hồi khiếu nại*. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú gốc: người đọc nhầm ticket. Sửa nhãn người thành FAIL; nhãn vàng cũng cần audit, không chỉ judge. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người (lệch nhỏ) | Lặp "Dạ" do gõ: lỗi trình bày, không phải thái độ. Rubric: *lỗi gõ nhẹ không làm FAIL tone*. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ… xin loi…" | PASS | FAIL | Người | Mất dấu tiếng Việt là FAIL về chất lượng ngôn ngữ. Rubric: *reply không dấu = FAIL*. |

Nhận xét: 6/10 bất đồng là **false negative** của judge (bỏ sót lỗi xưng hô, mệnh lệnh, emoji, mất dấu); 4/10 là false positive (phạt quá tay chuyện xin lỗi, tiếng Anh, lỗi gõ). Sửa rubric ở các dòng trên nhắm vào cả hai hướng, rồi phải calibrate lại trên nhãn mới (không chấm lại trên chính 100 dòng này, vì đã dùng chúng để sửa rubric).

## Kết luận

- **helpful bị loại.** Recall 0.30: trong 30 reply người gán FAIL, judge chỉ bắt 9 (fn = 21). Precision 1.0 không cứu được: judge gần như luôn nói PASS, nên κ chỉ 0.375. Đọc các bất đồng (HL-015, HL-020, HL-043, HL-087…) thì phần lớn là reply **nói sai số tiền so với ledger** ("ledger ghi 40.000đ" nhưng reply nói 55.000đ), cộng với reply dài dòng xin lỗi và "Ok bạn, … xử lý rồi nhé" (không nêu kết quả). Judge đọc câu chữ trôi chảy và cho qua; nó không nhìn ledger. Dùng judge này làm gate nghĩa là để lọt chính FM-08. Vì vậy số tiền trong reply được chấm bằng **code** (`reply_matches_ledger`), không bằng judge.
- **tone_ok dùng được** cho tiêu chí giọng điệu, nhưng tỉ lệ lỗi phải báo theo số đã hiệu chỉnh Rogan-Gladen (0.28 quan sát → 0.30 ước lượng thật), và không đưa vào gate chặn release ở giai đoạn này (tiền và approval luôn là code).
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai; 10 bất đồng ở trên đã được dùng để sửa rubric nên không còn là held-out. Cần một bộ nhãn người mới (≥100 reply, 2 người gán, đo κ giữa người) trước khi tin κ = 0.757.
