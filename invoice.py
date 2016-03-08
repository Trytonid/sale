# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from functools import wraps
from sql import Table

from trytond.model import Workflow, fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond import backend

__all__ = ['Invoice', 'InvoiceLine']


def process_sale(func):
    @wraps(func)
    def wrapper(cls, invoices):
        pool = Pool()
        Sale = pool.get('sale.sale')
        with Transaction().set_context(_check_access=False):
            sales = [s for i in cls.browse(invoices) for s in i.sales]
        func(cls, invoices)
        with Transaction().set_context(_check_access=False):
            Sale.process(sales)
    return wrapper


class Invoice:
    __metaclass__ = PoolMeta
    __name__ = 'account.invoice'
    sale_exception_state = fields.Function(fields.Selection([
        ('', ''),
        ('ignored', 'Ignored'),
        ('recreated', 'Recreated'),
        ], 'Exception State'), 'get_sale_exception_state')
    sales = fields.Function(fields.One2Many('sale.sale', None, 'Sales'),
        'get_sales', searcher='search_sales')

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._error_messages.update({
                'reset_invoice_sale': ('You cannot reset to draft '
                    'an invoice generated by a sale.'),
                })

    @classmethod
    def get_sale_exception_state(cls, invoices, name):
        Sale = Pool().get('sale.sale')
        sales = Sale.search([
                ('invoices', 'in', [i.id for i in invoices]),
                ])

        recreated = tuple(i for p in sales for i in p.invoices_recreated)
        ignored = tuple(i for p in sales for i in p.invoices_ignored)

        states = {}
        for invoice in invoices:
            states[invoice.id] = ''
            if invoice in recreated:
                states[invoice.id] = 'recreated'
            elif invoice.id in ignored:
                states[invoice.id] = 'ignored'
        return states

    def get_sales(self, name):
        pool = Pool()
        SaleLine = pool.get('sale.line')
        sales = set()
        for line in self.lines:
            if isinstance(line.origin, SaleLine):
                sales.add(line.origin.sale.id)
        return list(sales)

    @classmethod
    def search_sales(cls, name, clause):
        return [('lines.origin.sale',) + tuple(clause[1:]) + ('sale.line',)]

    @classmethod
    def copy(cls, invoices, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('sales', None)
        return super(Invoice, cls).copy(invoices, default=default)

    @classmethod
    @process_sale
    def delete(cls, invoices):
        super(Invoice, cls).delete(invoices)

    @classmethod
    @process_sale
    def post(cls, invoices):
        super(Invoice, cls).post(invoices)

    @classmethod
    @process_sale
    def paid(cls, invoices):
        super(Invoice, cls).paid(invoices)

    @classmethod
    @process_sale
    def cancel(cls, invoices):
        super(Invoice, cls).cancel(invoices)

    @classmethod
    @Workflow.transition('draft')
    def draft(cls, invoices):
        Sale = Pool().get('sale.sale')
        sales = Sale.search([
                ('invoices', 'in', [i.id for i in invoices]),
                ])
        if sales and any(i.state == 'cancel' for i in invoices):
            cls.raise_user_error('reset_invoice_sale')

        return super(Invoice, cls).draft(invoices)


class InvoiceLine:
    __metaclass__ = PoolMeta
    __name__ = 'account.invoice.line'

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().connection.cursor()
        sql_table = cls.__table__()

        super(InvoiceLine, cls).__register__(module_name)

        # Migration from 2.6: remove sale_lines
        rel_table_name = 'sale_line_invoice_lines_rel'
        if TableHandler.table_exist(rel_table_name):
            rel_table = Table(rel_table_name)
            cursor.execute(*rel_table.select(
                    rel_table.sale_line, rel_table.invoice_line))
            for sale_line, invoice_line in cursor.fetchall():
                cursor.execute(*sql_table.update(
                        columns=[sql_table.origin],
                        values=['sale.line,%s' % sale_line],
                        where=sql_table.id == invoice_line))
            TableHandler.drop_table(
                'sale.line-account.invoice.line', rel_table_name)

    @property
    def origin_name(self):
        pool = Pool()
        SaleLine = pool.get('sale.line')
        name = super(InvoiceLine, self).origin_name
        if isinstance(self.origin, SaleLine):
            name = self.origin.sale.rec_name
        return name

    @classmethod
    def _get_origin(cls):
        models = super(InvoiceLine, cls)._get_origin()
        models.append('sale.line')
        return models
