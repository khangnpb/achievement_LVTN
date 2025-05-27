{
    'name': 'DAC Project Extension',
    'version': '1.0',
    'category': 'Project',
    'summary': 'DAC Pancake Project Extension',
    'depends': ['base'],
    'data': [
        # 'security/ir.model.access.csv',
        # 'views/contents_view.xml',
        # 'views/menu.xml',
        'security/ir.model.access.csv', # Đảm bảo file này được khai báo TRƯỚC views
        'views/page_fm_views.xml',
        'data/ir_config_parameter_data.xml',
    ],
    'installable': True,
    'application': False,
}