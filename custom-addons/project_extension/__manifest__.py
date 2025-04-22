{
    'name': 'Project Extension',
    'version': '1.0',
    'category': 'Project',
    'summary': 'Thêm chức năng mở rộng cho Project',
    'depends': ['base','project'],
    'data': [
        'security/ir.model.access.csv',
        'views/contents_view.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
}