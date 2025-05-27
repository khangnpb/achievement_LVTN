import logging
import html2text # Đảm bảo thư viện này đã được cài đặt (pip install html2text)
import json # Mặc dù không dùng trực tiếp trong hàm này nhưng có thể cần cho attachments_json ở nơi khác
from odoo import models, fields, api, _
from datetime import datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)

class PageFmMessage(models.Model):
    _name = 'page.fm.message'
    _description = 'Page.fm Message'
    _order = 'inserted_at_fm asc, id asc'

    name = fields.Char(string="Short Content",
                    compute="_compute_display_name", 
                    store=True, help="Tóm tắt nội dung hoặc ID tin nhắn")
    message_fm_id = fields.Char(string="Message FM ID", required=True, index=True, copy=False)
    
    conversation_id = fields.Many2one(
        'page.fm.conversation', 
        string="Conversation", 
        required=True, 
        ondelete='cascade', 
        index=True
    )
    page_fm_page_id_related = fields.Many2one(
        related='conversation_id.page_fm_page_id',
        string="Page (Related)",
        store=True, 
        readonly=True
    )
    
    sender_name_fm = fields.Char(string="Sender Name (from API)")
    staff_name_fm = fields.Char(string="Staff Name (from API)") 
    
    content_html = fields.Html(string="Content", help="Nội dung tin nhắn dạng HTML từ API")
    attachments_json = fields.Text(string="Attachments (JSON)", help="Dữ liệu đính kèm dạng JSON thô từ API")
    
    inserted_at_fm = fields.Datetime(string="Time Sent (FM)", index=True)
    
    raw_json_message = fields.Text(string="Raw JSON Message", help="Toàn bộ JSON của tin nhắn từ API để tham khảo")

    _sql_constraints = [
        ('message_fm_id_conversation_uniq', 'unique(message_fm_id, conversation_id)', 'Message FM ID phải là duy nhất cho mỗi hội thoại!')
    ]

# Trong class PageFmMessage (models/page_fm_message_models.py)

    # @api.depends('content_html', 'message_fm_id', 'attachments_json')
    # def _compute_display_name(self):
    #     _logger.error(f"--- DIAGNOSTIC COMPUTE for records: {self.ids} ---")
    #     for record in self:
    #         record_id_for_log = record.id if record.id and not isinstance(record.id, models.NewId) else "NEW_RECORD"
    #         _logger.error(f"Processing record: {record_id_for_log}")
            
    #         new_name_value = f"Diag Name for Msg {record_id_for_log}"
            
    #         try:
    #             record.name = new_name_value
    #             _logger.error(f"ASSIGNED IN-MEMORY: record {record_id_for_log}.name = '{new_name_value}'")
                
    #             # Chỉ flush và refresh cho bản ghi đã tồn tại (có ID số)
    #             if record.id and not isinstance(record.id, models.NewId):
    #                 _logger.error(f"Attempting to FLUSH 'name' for record {record.id}")
    #                 record.flush_recordset(['name']) # Ép ghi trường 'name' xuống DB
    #                 _logger.error(f"COMPLETED FLUSH for 'name' for record {record.id}")
                    
    #                 _logger.error(f"Attempting to REFRESH record {record.id} from DB")
    #                 record.refresh() # Đọc lại bản ghi từ DB
    #                 _logger.error(f"COMPLETED REFRESH for record {record.id}. Value of record.name from DB: '{record.name}'")
                    
    #                 # Kiểm tra xem giá trị có đúng sau khi refresh không
    #                 if record.name != new_name_value:
    #                     _logger.error(f"!!! MISMATCH AFTER REFRESH for record {record.id}: Expected '{new_name_value}', Got '{record.name}'")
    #                     # Nếu khác, thử gán lại một lần nữa sau khi refresh (rất không bình thường)
    #                     # record.name = new_name_value 
    #                     # _logger.error(f"RE-ASSIGNED after refresh: record {record.id}.name = '{new_name_value}'")


    #         except Exception as e_compute_assign:
    #             _logger.error(f"EXCEPTION during name assignment or flush/refresh for {record_id_for_log}: {e_compute_assign}", exc_info=True)
    #             try:
    #                 # Fallback cuối cùng nếu có lỗi
    #                 record.name = f"ErrorFallback {record_id_for_log}"
    #                 _logger.error(f"Assigned ErrorFallbackName to {record_id_for_log}")
    #             except Exception as e_fallback_final:
    #                 _logger.error(f"CRITICAL EXCEPTION assigning ErrorFallbackName to {record_id_for_log}: {e_fallback_final}", exc_info=True)

    #     _logger.error(f"--- FINISHED DIAGNOSTIC COMPUTE for records: {self.ids} ---")

    @api.depends('content_html', 'message_fm_id', 'attachments_json')
    def _compute_display_name(self):
        for record in self:
            if record.content_html:
                try:
                    h = html2text.HTML2Text()
                    h.ignore_links = True # Tùy chọn: bỏ qua link
                    h.ignore_images = True # Tùy chọn: bỏ qua ảnh
                    plain_text = h.handle(record.content_html).strip()
                except Exception as e:
                    _logger.warning(f"Lỗi khi chuyển HTML sang text cho message {record.id}: {e}")
                    plain_text = _("[Lỗi hiển thị nội dung]")
                
                record.name = (plain_text[:75] + '...') if len(plain_text) > 75 else plain_text
            elif record.attachments_json and record.attachments_json != '[]':
                record.name = _("[Message with attachments]")
            else:
                record.name = f"Msg: {record.message_fm_id or record.id or 'N/A'}"


    def action_view_raw_json(self):
        self.ensure_one()
        # Giả sử tên module của bạn là CRM_DAC
        # Nếu tên module khác, hãy thay đổi 'CRM_DAC.view_page_fm_message_raw_json_form' cho phù hợp
        view_id = False
        try:
            view_id = self.env.ref('CRM_DAC.view_page_fm_message_raw_json_form').id
        except ValueError as e: # External ID not found
             _logger.error(f"Không tìm thấy XML ID 'CRM_DAC.view_page_fm_message_raw_json_form': {e}")
             # Có thể fallback mở một form view mặc định hoặc báo lỗi
             # For now, let it raise error or return an empty view list if not found
             pass


        return {
            'type': 'ir.actions.act_window',
            'name': _('Raw Message JSON'),
            'res_model': 'page.fm.message',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'views': [(view_id, 'form')] if view_id else [], 
        }