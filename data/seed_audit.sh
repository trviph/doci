#!/usr/bin/env bash
# Seed the doci userdata layer from the payment-document audit ruleset.
# Distilled into: dossiers (payment categories) + document defs (base + per-category)
# + agent rules (cross-cutting checks) + knowledge (reference material).
set -u
B="${B:-http://localhost:8011}"

api()     { curl -fsS -X "$1" "$B$2" -H 'content-type: application/json' -d "$3"; }
dossier() { api POST /dossiers "{\"key\":\"$1\",\"name\":\"$2\",\"description\":\"$3\"}" >/dev/null && echo "  dossier  $1"; }
doc()     { api PUT "/dossiers/$1/documents" "{\"key\":\"$2\",\"name\":\"$3\",\"description\":\"$4\",\"look_for\":\"$5\"}" >/dev/null; }
rule()    { api POST /agent-rules "{\"key\":\"$1\",\"name\":\"$2\",\"body\":\"$3\"}" >/dev/null && echo "  rule     $1"; }
link()    { api PUT "/agent-rules/$1/dossiers" "{\"dossier_keys\":$2}" >/dev/null; }
know()    { api POST /knowledge "{\"key\":\"$1\",\"name\":\"$2\",\"description\":\"$3\",\"body\":\"$4\"}" >/dev/null && echo "  knowledge $1"; }

echo "== dossiers (payment categories) =="
dossier marketing        "Thanh toán Marketing"                  "Hồ sơ thanh toán nhóm marketing"
dossier thiet-bi-logistics "Thanh toán Thiết bị, Kho và Vận chuyển" "Hồ sơ thanh toán thiết bị, kho, logistics"
dossier dich-vu-so       "Thanh toán Dịch vụ số và Khuyến mãi"    "Hồ sơ thanh toán dịch vụ số, voucher, khuyến mãi"
dossier phap-ly-thue     "Thanh toán Pháp lý, Lending và Thuế"    "Hồ sơ thanh toán pháp lý, lending, thuế"
dossier co-so-vat-chat   "Thanh toán Cơ sở vật chất và Admin"     "Hồ sơ thanh toán cơ sở vật chất, admin"
dossier nhan-su-khac     "Thanh toán Nhân sự và Chi phí khác"     "Hồ sơ thanh toán nhân sự và chi phí khác"

ALL='["marketing","thiet-bi-logistics","dich-vu-so","phap-ly-thue","co-so-vat-chat","nhan-su-khac"]'

echo "== base documents (bộ chứng từ nền §2) on every dossier =="
for D in marketing thiet-bi-logistics dich-vu-so phap-ly-thue co-so-vat-chat nhan-su-khac; do
  doc "$D" pr              "Payment/Purchase Request"            "Chứng từ khởi tạo yêu cầu chi/mua hàng. Tiêu đề: Đề nghị thanh toán, Giấy đề nghị thanh toán, Đề nghị mua hàng, Payment Request, Purchase Request, PR." "Đề nghị thanh toán/mua hàng: người lập, ngày lập, số tiền, mục đích; chữ ký người lập và người duyệt: tên và chức danh người ký"
  doc "$D" po-epr          "Purchase Order / ePR"                "Đơn đặt hàng hoặc ePR đã duyệt. Tiêu đề: Đơn đặt hàng, Purchase Order, PO, ePR." "PO/ePR được duyệt; số tiền và vendor khớp PR và hóa đơn; người duyệt: tên và chức danh"
  doc "$D" contract        "Hợp đồng / Agreement"                "Hợp đồng/thỏa thuận ràng buộc giữa các bên, gồm các điều khoản (Điều 1, Điều 2...). Tiêu đề: Hợp đồng, Hợp đồng kinh tế, Hợp đồng nguyên tắc, Hợp đồng dịch vụ, Contract, Agreement." "Hợp đồng còn hiệu lực nếu giao dịch thuộc diện cần hợp đồng; đại diện ký kết mỗi bên: tên + chức danh + đại diện bên nào; con dấu: tên tổ chức trên dấu của mỗi bên"
  doc "$D" phu-luc         "Phụ lục / Báo giá / Rate card"       "Phụ lục hợp đồng, bảng báo giá hoặc rate card. Tiêu đề: Phụ lục, Phụ lục hợp đồng, Báo giá, Bảng báo giá, Quotation, Rate card." "Đơn giá, điều khoản, phạm vi dịch vụ để đối chiếu nghiệm thu"
  doc "$D" invoice         "Hóa đơn"                             "Hóa đơn GTGT/điện tử, có MST và mã cơ quan thuế. Tiêu đề: Hóa đơn, Hóa đơn GTGT, Hóa đơn giá trị gia tăng, Invoice, HĐĐT." "Hóa đơn hợp lệ, có mã CQT nếu là HĐĐT, không quá 180 ngày; MST và số tiền"
  doc "$D" grn             "Nghiệm thu/Giao hàng (GRN/BBNT/PGH/BBBG)" "Chứng từ xác nhận đã nhận/bàn giao hàng hóa hoặc nghiệm thu dịch vụ. Tiêu đề: Biên bản nghiệm thu, Biên bản nghiệm thu - thanh lý, Biên bản nghiệm thu và thanh lý, Biên bản bàn giao, Phiếu giao hàng, Phiếu xuất kho kiêm giao hàng, Goods Receipt Note, GRN, BBNT, PGH, BBBG. Có chữ thanh lý vẫn là nghiệm thu, không phải hợp đồng." "Bằng chứng nhận hàng/dịch vụ phù hợp bản chất giao dịch; chữ ký nghiệm thu: tên + chức danh + đại diện bên A và bên B; con dấu: tên tổ chức trên dấu"
  doc "$D" payment-voucher "Phiếu chi / Payment voucher"         "Phiếu chi tiền nội bộ. Tiêu đề: Phiếu chi, Payment voucher." "Thông tin thanh toán; chữ ký phê duyệt: tên và chức danh người duyệt"
  doc "$D" bank-unc        "Sao kê / Ủy nhiệm chi"               "Sao kê ngân hàng hoặc lệnh/ủy nhiệm chi chuyển tiền. Tiêu đề: Ủy nhiệm chi, UNC, Lệnh chi, Sao kê tài khoản, Bank statement." "Bằng chứng đã/chờ thanh toán, khớp số tiền với hóa đơn và PV"
  echo "  base docs -> $D"
done

echo "== category-specific documents (§6) =="
# 6.1 Marketing
doc marketing talent-cccd   "CCCD diễn viên / Talent form"        "Căn cước công dân của diễn viên hoặc biểu mẫu thông tin diễn viên. Nhận biết: thẻ CCCD/CMND có ảnh và số định danh, hoặc talent form." "CCCD diễn viên, talent form; kiểm tra diễn viên stock, số lượng, dựng cảnh, khả năng tái sử dụng asset"
doc marketing media-report  "Report hình ảnh / KV / bài đăng"     "Báo cáo hình ảnh, key visual hoặc capture bài đăng đã thực hiện. Nhận biết: ảnh chụp màn hình bài đăng, hình ảnh KV kèm chú thích nghiệm thu." "Capture bài đăng, report hình ảnh/KV thực tế khớp nghiệm thu"
doc marketing media-plan    "Media plan vs actual spending"       "Kế hoạch truyền thông và chi tiêu thực tế. Nhận biết: bảng media plan/actual spending, screenshot nền tảng quảng cáo Google, Facebook, TikTok, Adtima." "Media plan và actual spending; screenshot Google/Facebook/TikTok/Adtima; nghiệm thu theo view/click nhân CPV/CPM"
doc marketing kol-report    "Report KOL và Seeding"               "Báo cáo hiệu quả KOL và seeding. Nhận biết: bảng hoặc capture view, comment, share, link bài KOL." "Capture view/comment/share; nội dung đúng thương hiệu; so CPE/CPV với rate card; check duplicate link"
doc marketing ooh-report    "Report OOH / dán xe"                 "Báo cáo quảng cáo ngoài trời (OOH) hoặc dán xe. Nhận biết: hình ảnh thực tế biển/xe, số liệu, giấy phép quảng cáo." "Số liệu và hình ảnh thực tế; giấy phép quảng cáo; đối chiếu chi phí dán xe và chi phí trả tài xế"
doc marketing posm-bbbg     "BBBG POSM / Standee / Brochure"      "Biên bản bàn giao POSM, standee hoặc brochure. Tiêu đề: Biên bản bàn giao POSM/standee/brochure, kèm hình ảnh sản phẩm." "BBBG và hình ảnh sản phẩm; tỷ lệ sử dụng, tồn kho, chi phí lưu kho"
# 6.2 Thiết bị, kho, vận chuyển
doc thiet-bi-logistics bbbg-thiet-bi  "BBBG thiết bị (Nhất Tín/PIC Gfin)" "Biên bản bàn giao thiết bị có chữ ký nhận hàng (Nhất Tín/PIC Gfin). Tiêu đề: Biên bản bàn giao thiết bị, kèm danh sách serial/IMEI, model." "Chữ ký nhận hàng Nhất Tín/PIC Gfin; khớp số lượng, model, giá giữa hóa đơn và email đặt hàng; serial/IMEI list"
doc thiet-bi-logistics bb-doi-soat-snpl "Danh sách hóa đơn và BB đối soát (SNPL)" "Danh sách hóa đơn kèm biên bản đối soát SNPL. Tiêu đề: Biên bản đối soát, Bảng kê hóa đơn, Danh sách hóa đơn." "Số tiền trên list hóa đơn khớp biên bản đối soát"
doc thiet-bi-logistics email-pic-kho  "Email confirm PIC Gfin (kho)" "Email xác nhận của PIC Gfin về kho. Nhận biết: nội dung email confirm số lượng/số tiền, Monthly Inventory." "Số tiền email PIC Gfin khớp bảng kê và hóa đơn; Monthly Inventory đầu tháng"
doc thiet-bi-logistics bang-ke-van-chuyen "Bảng kê và bill vận chuyển" "Bảng kê chi phí vận chuyển kèm các bill cước. Tiêu đề: Bảng kê vận chuyển, bill/cước vận chuyển." "Bảng kê chi phí và bill từng cước; phát hiện cước vượt trội hoặc bất hợp lý"
# 6.3 Dịch vụ số và khuyến mãi
doc dich-vu-so bb-doi-soat-sms "BB đối soát SMS / Vietguys"      "Biên bản đối soát dịch vụ SMS (Vietguys) có chữ ký và mộc. Tiêu đề: Biên bản đối soát SMS, Biên bản đối soát Vietguys." "BB đối soát có chữ ký và mộc; đối chiếu 3 chiều bảng kê = hóa đơn = report ảnh hệ thống; đơn giá khớp phụ lục"
doc dich-vu-so voucher-list    "Danh sách / bảng kê voucher"     "Danh sách hoặc bảng kê voucher. Nhận biết: bảng liệt kê mã/số lượng voucher, biên bản nhận voucher giấy." "Số tiền và số lượng khớp hóa đơn và email PIC Gfin; voucher giấy có chữ ký PIC nhận trên BB"
doc dich-vu-so email-pic-so    "Email confirm PIC Gfin (dịch vụ số)" "Email xác nhận của PIC Gfin cho dịch vụ số. Nhận biết: email confirm số tiền dịch vụ số khớp bảng kê/hóa đơn." "Số tiền email, hóa đơn và bảng kê khớp nhau"
doc dich-vu-so thong-bao-doit  "Thông báo và chấp nhận DOIT"     "Thông báo hoặc biên bản chấp nhận chương trình khuyến mãi (DOIT) có chữ ký và mộc. Tiêu đề: Thông báo khuyến mãi, Biên bản chấp nhận DOIT." "BB/thông báo KM có chữ ký và mộc; data khớp hóa đơn"
# 6.4 Pháp lý, lending, thuế
doc phap-ly-thue timesheet        "Timesheet tư vấn"             "Bảng kê giờ tư vấn (timesheet). Tiêu đề: Timesheet, Bảng kê giờ tư vấn, kèm cột ngày/giờ/nội dung công việc." "Timesheet theo giờ; soi nội dung bất hợp lý, khai khống, double-charge giờ"
doc phap-ly-thue bao-cao-tham-dinh "Báo cáo thẩm định"          "Báo cáo kết quả thẩm định. Tiêu đề: Báo cáo thẩm định, Báo cáo kết quả thẩm định." "Báo cáo kết quả thẩm định hợp lệ"
doc phap-ly-thue bb-doi-soat-lending "BB đối soát lending"      "Biên bản đối soát lending có chữ ký nháy PIC Gfin và Head ký. Tiêu đề: Biên bản đối soát lending." "BB đối soát PIC Gfin ký nháy, Head ký; số tiền sau ký khớp hóa đơn"
doc phap-ly-thue giay-nop-thue    "Giấy nộp ngân sách nhà nước" "Giấy nộp tiền vào ngân sách nhà nước. Tiêu đề: Giấy nộp tiền vào NSNN, Giấy nộp ngân sách nhà nước." "Giấy nộp tiền khớp báo cáo chương trình tạo ra khoản thuế"
# 6.5 Cơ sở vật chất và admin
doc co-so-vat-chat cham-cong-bao-ve "Bảng chấm công bảo vệ"     "Bảng chấm công nhân viên bảo vệ. Tiêu đề: Bảng chấm công, kèm lưới ngày công theo từng người." "Đủ base docs và khớp chấm công"
doc co-so-vat-chat file-ccdc        "File quản lý CCDC"          "File hoặc bảng quản lý công cụ dụng cụ (CCDC), small asset. Tiêu đề: File quản lý CCDC, Danh mục CCDC." "Ghi nhận small asset; kiểm tra tồn kho trước khi duyệt mua mới"
doc co-so-vat-chat hop-dong-thue-vp "Hợp đồng/phụ lục thuê văn phòng" "Hợp đồng hoặc phụ lục thuê văn phòng. Tiêu đề: Hợp đồng thuê văn phòng, Phụ lục thuê văn phòng." "Đơn giá thuê khớp hợp đồng và phụ lục"
doc co-so-vat-chat bang-ke-cmc      "Bảng kê và email confirm (điện thoại/CMC)" "Bảng kê cước điện thoại/CMC kèm email xác nhận. Tiêu đề: Bảng kê cước, Email confirm CMC." "Số tiền email confirm khớp hóa đơn và thông báo"
# 6.6 Nhân sự và chi phí khác
doc nhan-su-khac email-approve-trip "Email approve công tác phí" "Email phê duyệt công tác phí kèm báo giá trip/option. Nhận biết: nội dung email approve công tác phí." "Phê duyệt đúng thẩm quyền; báo giá trip/option và email confirm option"
doc nhan-su-khac concur-claim       "Đối chiếu Concur (engagement)" "Bản đối chiếu chi phí trên hệ thống Concur. Nhận biết: report/screenshot Concur, số dư engagement remaining." "Không kê hóa đơn trùng phần đã claim qua Concur; kiểm tra remaining"
doc nhan-su-khac ban-dich-dong-dau  "Bản gốc và bản dịch đóng dấu" "Tài liệu bản gốc kèm bản dịch có đóng dấu đỏ của đơn vị dịch. Nhận biết: cặp văn bản gốc và bản dịch công chứng/đóng dấu." "Xác minh chữ ký/dấu đỏ; vendor đóng dấu"
doc nhan-su-khac email-outsourcing  "Email confirm nhân sự outsourcing" "Email xác nhận chi phí nhân sự outsourcing. Nhận biết: email confirm số tiền nhân sự thuê ngoài." "Số tiền duyệt trên email khớp hóa đơn"
echo "  category docs done"

echo "== agent rules (cross-cutting audit checks) =="
rule du-chung-tu "Đủ chứng từ" "## Kiểm tra đủ chứng từ\n\nMỗi bộ hồ sơ thanh toán phải có đủ bộ chứng từ nền: PR, PO/ePR, Hợp đồng (nếu thuộc diện), Phụ lục/Báo giá, Hóa đơn, Nghiệm thu (GRN/BBNT/PGH/BBBG), Phiếu chi, Sao kê/UNC.\n\n- Phải đủ chứng từ bổ sung theo từng loại thanh toán của dossier.\n- Ngoại lệ: tạm ứng có thể thiếu GRN và Bank; dịch vụ một lần dưới 10 triệu VND có thể thiếu Hợp đồng nếu có báo giá/phê duyệt thay thế.\n- Thiếu chứng từ bắt buộc: BLOCK."
rule so-khop-so-tien "So khớp số tiền" "## So khớp số tiền\n\n- PR khớp PO (sai: Medium/High)\n- PO khớp hóa đơn (sai: High)\n- Hóa đơn khớp số tiền thanh toán (sai: High)\n- Sai lệch cho phép tối đa 1 phần trăm hoặc 100.000 VND, lấy ngưỡng nhỏ hơn."
rule so-khop-vendor "So khớp vendor và tham chiếu" "## So khớp vendor\n\n- Tên NCC trên PR/PO/HĐ/hóa đơn/PV khớp nhau, fuzzy match tối thiểu 85 phần trăm (Medium).\n- MST 10 hoặc 13 số, khớp trên các chứng từ (High).\n- Số hợp đồng và số PO tham chiếu hợp lệ trên hóa đơn (Medium).\n- NCC/MST không nằm trong blacklist: vi phạm là BLOCK."
rule chuoi-ngay-thang "Chuỗi ngày tháng" "## Chuỗi ngày chuẩn\n\nPR <= PO <= GRN/BBNT/PGH/BBBG <= Hóa đơn <= Thanh toán\n\n- PR không sau PO; PO trước nghiệm thu; nghiệm thu phù hợp hóa đơn; không thanh toán trước khi có hóa đơn trừ tạm ứng được duyệt.\n- Backdating PO/PR trên 30 ngày: High/Critical.\n- Tuổi hóa đơn không quá 180 ngày."
rule chu-ky-loa-sod "Chữ ký, LOA và phân quyền" "## Chữ ký, phê duyệt, SoD\n\n- Chứng từ kế toán đủ người lập và người duyệt; payment voucher có chữ ký phê duyệt (High).\n- Mỗi chữ ký phải xác định được người ký: tên, chức danh, và đại diện bên nào. Chữ ký không rõ danh tính (chỉ có nét ký, không có tên/chức danh): High; NEEDS REVIEW nếu không đủ dữ liệu để xác minh.\n- Mỗi con dấu/mộc phải thể hiện tên tổ chức trên dấu, khớp với bên ký tương ứng. Mộc không có thông tin tổ chức hoặc không khớp bên ký: High.\n- Biên bản đối soát có chữ ký và mộc với dịch vụ cần đối soát (High).\n- LOA: người duyệt đúng cấp theo số tiền, tham chiếu knowledge loa-authority-matrix.\n- SoD: người tạo PR khác người duyệt PO; người duyệt PO khác người duyệt thanh toán."
rule thue-hoa-don "Thuế và hóa đơn" "## Thuế và hóa đơn\n\n- VAT rate hợp lệ: 0, 5, 8, 10 phần trăm.\n- VAT = Subtotal nhân VAT rate, sai lệch tối đa 0,5 phần trăm.\n- Hóa đơn điện tử phải có mã cơ quan thuế nếu thuộc diện.\n- Ngày hóa đơn không ở tương lai, không quá 180 ngày.\n- FCT cho nhà thầu nước ngoài; PIT 10 phần trăm cho cá nhân nhận trên 2 triệu mỗi lần."
rule rui-ro-gian-lan "Rủi ro và gian lận" "## Rủi ro và gian lận\n\n- Duplicate payment: cùng MST + số hóa đơn + số tiền trong 30 ngày (High).\n- Split payment: hơn 3 hóa đơn cùng vendor trong 7 ngày, mỗi hóa đơn dưới ngưỡng duyệt (High).\n- Thanh toán cuối tuần/ngày lễ không pre-approval (Medium); rush PR đến payment dưới 1 ngày với giao dịch trên 20 triệu (Medium).\n- Vendor đổi tài khoản ngân hàng trong 30 ngày (High); vendor mới dưới 90 ngày và giao dịch trên 50 triệu (High).\n- Round number trên 50 triệu (Low/Medium); vendor concentration trên 30 phần trăm warning, trên 50 phần trăm critical; budget usage trên 80 phần trăm warning, trên 95 phần trăm critical."
echo "  -- link every rule to all dossiers --"
for R in du-chung-tu so-khop-so-tien so-khop-vendor chuoi-ngay-thang chu-ky-loa-sod thue-hoa-don rui-ro-gian-lan; do
  link "$R" "$ALL"
done

echo "== knowledge (reference material) =="
know loa-authority-matrix "LOA / Authority matrix" "Bảng phân quyền duyệt theo số tiền (PLACEHOLDER, cần cập nhật dữ liệu chính thức)" "## LOA / Authority matrix (PLACEHOLDER)\n\n| Giá trị thanh toán | Người duyệt yêu cầu |\n|---|---|\n| <= 20 triệu | Trưởng phòng |\n| <= 100 triệu | Giám đốc bộ phận |\n| <= 200 triệu | Giám đốc |\n| <= 500 triệu | CFO + Giám đốc |\n| > 500 triệu | CEO + CFO |\n\nGhi chú: cần thay bằng ma trận chính thức khi nhận được."
know nguong-kiem-tra "Ngưỡng và thời hạn kiểm tra" "Các ngưỡng số tiền, thời hạn và cửa sổ thời gian dùng cho rule" "## Ngưỡng và thời hạn\n\n- Sai lệch số tiền cho phép: tối đa 1 phần trăm hoặc 100.000 VND (lấy nhỏ hơn).\n- Tuổi hóa đơn tối đa: 180 ngày.\n- Backdating cảnh báo: trên 30 ngày.\n- Duplicate payment: cửa sổ 30 ngày, fuzzy match >= 95 phần trăm.\n- Split payment: hơn 3 hóa đơn cùng vendor trong 7 ngày.\n- Vendor mới: dưới 90 ngày và giao dịch trên 50 triệu.\n- Round number bất thường: trên 50 triệu.\n- Vendor concentration: trên 30 phần trăm warning, trên 50 phần trăm critical.\n- Budget usage: trên 80 phần trăm warning, trên 95 phần trăm critical.\n- Fuzzy match tên NCC: tối thiểu 85 phần trăm."
know vat-thue "Thuế suất VAT và khấu trừ" "Thuế suất VAT hợp lệ, công thức và quy tắc FCT/PIT" "## Thuế\n\n- VAT rate hợp lệ: 0, 5, 8, 10 phần trăm.\n- VAT = Subtotal nhân VAT rate, sai lệch tối đa 0,5 phần trăm.\n- Hóa đơn điện tử có mã CQT nếu thuộc diện.\n- FCT: nhà thầu nước ngoài khấu trừ theo loại hàng/dịch vụ.\n- PIT: cá nhân nhận trên 2 triệu mỗi lần khấu trừ 10 phần trăm; cá nhân có hợp đồng theo dõi ngưỡng năm."
know vendor-list "Vendor blacklist / whitelist" "Danh sách NCC bị cấm và NCC được duyệt (PLACEHOLDER)" "## Vendor list (PLACEHOLDER)\n\n- Blacklist: (cập nhật sau) - NCC/MST trong danh sách này thì BLOCK.\n- Whitelist: (cập nhật sau) - NCC đã thẩm định.\n\nGhi chú: cần nạp dữ liệu chính thức."
know trang-thai-ho-so "Tiêu chí kết luận hồ sơ" "Điều kiện PASS / NEEDS REVIEW / FAIL của một bộ hồ sơ" "## Kết luận trạng thái\n\n- PASS: đủ chứng từ nền, đủ chứng từ bổ sung theo loại, không có lỗi High/Critical.\n- NEEDS REVIEW: có cảnh báo Medium/Low hoặc thiếu bằng chứng phụ nhưng chưa ảnh hưởng trực tiếp thanh toán.\n- FAIL/BLOCK: thiếu chứng từ bắt buộc, sai số tiền trọng yếu, hóa đơn/thuế không hợp lệ, sai LOA/SoD nghiêm trọng, vendor blacklist, duplicate payment, hoặc hợp đồng đã ngưng."
know chuoi-ngay-chuan "Chuỗi ngày chuẩn của hồ sơ" "Thứ tự thời gian hợp lệ giữa các chứng từ" "## Chuỗi ngày chuẩn\n\nPR <= PO <= GRN/BBNT/PGH/BBBG <= Hóa đơn <= Thanh toán\n\nMọi sai lệch khỏi thứ tự này cần được flag theo rule chuoi-ngay-thang."

echo "== done =="
