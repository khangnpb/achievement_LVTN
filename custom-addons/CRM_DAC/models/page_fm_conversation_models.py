import requests
import json
import logging
from odoo import models, fields, api, _
from datetime import datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)

PAGES_FM_MESSAGES_API_BASE_URL = 'https://pages.fm/api/public_api/v1'
PAGES_FM_API_V1_BASE_URL = "https://pages.fm/api/v1" # Cần cho generate_page_specific_access_token nếu gọi từ đây

class PageFmConversation(models.Model):
    _name = 'page.fm.conversation'
    _description = 'Page.fm Conversation'
    _order = 'updated_at_fm desc'

    name = fields.Char(string="Customer Name", compute='_compute_name', store=True, help="Tên khách hàng hoặc ID hội thoại")
    conversation_fm_id = fields.Char(string="Conversation FM ID", required=True, index=True, copy=False, help="ID gốc của hội thoại từ API")
    
    page_fm_page_id = fields.Many2one(
        'page.fm.page', 
        string="Page.fm Page", 
        required=True, 
        ondelete='cascade',
        index=True,
        help="Trang Page.fm mà hội thoại này thuộc về"
    )
    page_fm_id_str_related = fields.Char(related='page_fm_page_id.page_fm_id_str', string="Page FM ID (Related)", store=True, readonly=True)

    customer_fm_id = fields.Char(string="Customer FM ID (for API)", index=True, copy=False, help="Customer ID (UUID) từ API, dùng để lấy tin nhắn chi tiết")
    customer_name_fm = fields.Char(string="Customer Name (from API)", help="Tên khách hàng từ API")
    last_message_snippet = fields.Text(string="Last Message Snippet", help="Đoạn tin nhắn cuối cùng")
    
    updated_at_fm = fields.Datetime(string="Last Updated (FM)", index=True, help="Thời điểm cập nhật cuối cùng của hội thoại từ API")
    
    is_unread_fm = fields.Boolean(string="Is Unread", help="Đánh dấu hội thoại là chưa đọc (dựa trên logic !conv.seen từ API)")
    platform_fm = fields.Char(string="Platform (FM)", help="Nền tảng của hội thoại (Zalo, Facebook, Instagram, etc.) được suy ra từ API")

    message_ids = fields.One2many('page.fm.message', 'conversation_id', string="Messages")
    message_count = fields.Integer(string="Message Count", compute='_compute_message_count', store=True)
    last_message_sync_fm = fields.Datetime(string="Last Message Sync (FM)", readonly=True, help="Thời điểm cuối cùng đồng bộ tin nhắn cho hội thoại này.")

    _sql_constraints = [
        ('conversation_fm_id_page_uniq', 'unique(conversation_fm_id, page_fm_page_id)', 'Conversation FM ID phải là duy nhất cho mỗi trang!')
    ]

    @api.depends('customer_name_fm', 'conversation_fm_id')
    def _compute_name(self):
        for record in self:
            if record.customer_name_fm and record.customer_name_fm not in ['Khách ẩn danh', '']:
                record.name = record.customer_name_fm
            elif record.conversation_fm_id:
                record.name = f"Conv: {record.conversation_fm_id}"
            else:
                record.name = _("N/A")

    @api.depends('message_ids')
    def _compute_message_count(self):
        for record in self:
            record.message_count = len(record.message_ids)

    def _fetch_message_batch(self, page_specific_access_token, current_count_offset=0):
        self.ensure_one()
        page_fm_id = self.page_fm_page_id.page_fm_id_str
        conv_fm_id = self.conversation_fm_id
        customer_api_id = self.customer_fm_id

        if not all([page_fm_id, conv_fm_id, customer_api_id, page_specific_access_token]):
            _logger.error(f"Thiếu thông tin cần thiết để lấy tin nhắn cho hội thoại {conv_fm_id} của trang {page_fm_id}.")
            return None

        messages_api_url = f"{PAGES_FM_MESSAGES_API_BASE_URL}/pages/{page_fm_id}/conversations/{conv_fm_id}/messages?page_access_token={page_specific_access_token}&customer_id={customer_api_id}&conversation_id={conv_fm_id}&page_id={page_fm_id}"
        if current_count_offset > 0:
            messages_api_url += f"&current_count={current_count_offset}"
        
        _logger.info(f"API Call: Fetch Message Batch for Conv {conv_fm_id} (offset {current_count_offset}) - URL: {messages_api_url}")

        try:
            response = requests.get(messages_api_url, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data
        except Exception as e:
            _logger.error(f"Lỗi khi lấy lô tin nhắn cho hội thoại {conv_fm_id} (offset {current_count_offset}): {e}", exc_info=True)
            return None

    def action_sync_messages(self):
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token, không thể lấy page specific token.")
            # from odoo.exceptions import UserError # Bỏ comment nếu muốn raise lỗi cho user
            # raise UserError(_("Main Access Token chưa được cấu hình."))
            return False # Hoặc True tùy theo bạn muốn action button trả về gì khi lỗi

        for record in self: # Xử lý cho từng hội thoại nếu action được gọi trên nhiều bản ghi
            _logger.info(f"Bắt đầu đồng bộ tin nhắn cho hội thoại: {record.name} (FM ID: {record.conversation_fm_id})")
            
            page_specific_access_token = record.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_specific_access_token:
                _logger.error(f"Không thể tạo page specific token cho page {record.page_fm_page_id.name} để lấy tin nhắn cho hội thoại {record.conversation_fm_id}.")
                continue # Bỏ qua hội thoại này nếu không có token

            MessageEnv = self.env['page.fm.message']
            load_all_from_context = self.env.context.get('load_all', False)
            
            current_message_offset = 0
            if load_all_from_context:
                current_message_offset = record.message_count 
            
            max_loops_load_all = 10 
            loop_count = 0
            new_messages_fetched_in_this_run = False

            while True:
                loop_count += 1
                if load_all_from_context and loop_count > max_loops_load_all:
                    _logger.warning(f"Đã đạt giới hạn {max_loops_load_all} vòng lặp khi tải tất cả tin nhắn cho hội thoại {record.conversation_fm_id}.")
                    break

                message_batch_data = record._fetch_message_batch(page_specific_access_token, current_message_offset)

                if not message_batch_data or not message_batch_data.get('success'):
                    _logger.error(f"Không thể lấy lô tin nhắn (offset {current_message_offset}) cho hội thoại {record.conversation_fm_id}.")
                    if not load_all_from_context and loop_count == 1: break
                    break 

                api_messages = message_batch_data.get('messages')
                if not isinstance(api_messages, list):
                    _logger.error(f"Dữ liệu messages (offset {current_message_offset}) cho hội thoại {record.conversation_fm_id} không phải là list.")
                    if not load_all_from_context and loop_count == 1: break
                    break

                if not api_messages:
                    _logger.info(f"Không có thêm tin nhắn nào (offset {current_message_offset}) cho hội thoại {record.conversation_fm_id}.")
                    break
                
                _logger.info(f"Lấy được {len(api_messages)} tin nhắn (offset {current_message_offset}) cho hội thoại {record.conversation_fm_id}.")
                new_messages_fetched_in_this_run = True

                for msg_data in api_messages:
                    if not isinstance(msg_data, dict) or not msg_data.get('id'):
                        _logger.warning(f"Bỏ qua dữ liệu tin nhắn không hợp lệ: {msg_data}")
                        continue

                    msg_fm_id = msg_data.get('id')
                    existing_msg = MessageEnv.search([
                        ('message_fm_id', '=', msg_fm_id),
                        ('conversation_id', '=', record.id)
                    ], limit=1)

                    inserted_at_api = msg_data.get('inserted_at', datetime.now().isoformat())
                    inserted_at_odoo = False
                    try:
                        dt_obj = datetime.fromisoformat(inserted_at_api.replace('Z', '+00:00'))
                        inserted_at_odoo = dt_obj.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                    except ValueError:
                        _logger.error(f"Lỗi parse inserted_at cho tin nhắn {msg_fm_id}: {inserted_at_api}")
                        inserted_at_odoo = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                    
                    msg_content_html = msg_data.get('message', '')
                    
                    message_values = {
                        'message_fm_id': msg_fm_id,
                        'conversation_id': record.id,
                        'sender_name_fm': msg_data.get('from', {}).get('name'),
                        'staff_name_fm': msg_data.get('from', {}).get('admin_name'),
                        'content_html': msg_content_html,
                        'attachments_json': json.dumps(msg_data.get('attachments')) if msg_data.get('attachments') else False,
                        'inserted_at_fm': inserted_at_odoo,
                        'raw_json_message': json.dumps(msg_data)
                    }
                    
                    try:
                        if not existing_msg:
                            MessageEnv.create(message_values)
                        else:
                            pass 
                    except Exception as e_create:
                        _logger.error(f"Lỗi khi tạo/cập nhật tin nhắn FM ID {msg_fm_id} cho hội thoại {record.conversation_fm_id}: {e_create}", exc_info=True)
                
                current_message_offset += len(api_messages)
                
                if len(api_messages) < 30 or not load_all_from_context: # API thường trả về 30 tin/batch
                    break 
            
            record.write({'last_message_sync_fm': datetime.now()})
            if new_messages_fetched_in_this_run :
                 record.invalidate_recordset(['message_count'])
            _logger.info(f"Hoàn tất đồng bộ tin nhắn cho hội thoại: {record.name} (FM ID: {record.conversation_fm_id})")
        
        # Action button nên trả về một action để refresh view hoặc không trả về gì (None)
        # Nếu muốn refresh view hiện tại (ví dụ: form view của conversation)
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
        # Hoặc nếu không cần refresh ngay, return True hoặc không return gì
        # return True