# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-014@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, item E-014, report `reports/eval_seeded_regression.json` (run `E-seeded_regression-<ngày>-7c78`) |
| Triệu chứng | Lab 8 grader FAIL (`proposal_mismatch`). `refund_amount_correct` = False: ledger ghi **90.000** trong khi nhãn là 120.000. `reply_matches_ledger` = False: reply nói "Dạ, LogiX đã hoàn **120.000đ** cho đơn O-515." Status `resolved` khớp nhãn, nên nhìn status thì tưởng đúng. |
| Bước sai đầu tiên | **Event 5 `proposal` `{"amount_vnd": 120000}`**: agent gửi host 120.000 thay vì quote đầy đủ 150.000. |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` chỉ có field allowlist. Event 2 `investigator` đọc đúng order O-515 (`delivered_late`, `damage_verified`). Event 3 `quote` đúng: 150.000, `clause_ids` SHIP-LATE-03 + DMG-04, lấy số lớn nhất. Event 4 `refund_history` đúng: đơn đã hoàn 30.000. Đến event 5 agent tự trừ 150.000 − 30.000 = 120.000, trái luật "truyền quote đầy đủ, host tự trừ". Host trừ thêm 30.000 lần nữa → ledger 90.000. Event 6 `reply` sai theo (báo số agent tự tính). |
| Failure mode | **FM-05** pre_deducted (nguyên nhân), kéo theo **FM-08** misreport (reply 120.000 ≠ ledger 90.000) |
| Đối chứng | `fixed C-014@11`: event 1–3 giống hệt, **không có** event `refund_history` và `proposal`; event 4 là `reply` "120.000đ"; host nhận 150.000, tự trừ 30.000, ledger 120.000 = nhãn; Lab 8 grader PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_c014_first_wrong_step_is_pre_deducted_proposal` (assert event `proposal` 120.000 đứng ngay sau `quote` 150.000 + `refund_history`; `FullQuotePassed`, `RefundAmountCorrect`, `ReplyMatchesLedger` đều False) và `test_lab9_trace_case_c014_fixed_control_is_clean` (cả 3 grader True trên `fixed`). Đã chạy: fail-đúng trên variant lỗi, pass trên `fixed`. Grader mức trajectory `full_quote_passed` (thêm vào `metric_spec.yaml`) bắt chính bước sai đầu tiên, không chỉ hậu quả trên ledger. |
| Chưa chắc chắn | Trace không cho biết *vì sao* agent trừ trước (MockLLM không có lập luận); chỉ chứng minh được hành vi. Với LLM thật có thể có biến thể trừ trước mà **không** ghi event `proposal` riêng: khi đó chỉ còn `refund_amount_correct` trên ledger bắt được. Case cũng không chứng minh lỗi xảy ra với mọi đơn đã hoàn một phần: chỉ C-008, C-013, C-014 trong eval set v1 có lịch sử hoàn. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
