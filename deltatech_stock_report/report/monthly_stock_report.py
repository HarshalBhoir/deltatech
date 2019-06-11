# -*- coding: utf-8 -*-
# ©  2008-2018 Fekete Mihai <mihai.fekete@forbiom.eu>
#              Dorin Hongu <dhongu(@)gmail(.)com
# See README.rst file on addons root folder for license details

from dateutil.relativedelta import relativedelta
from openerp import api, fields, models, _


# todo: de verificat ca sunt utilizate corect unitatile de masura!

class MonthlyStockReport(models.TransientModel):
    _name = 'stock.monthly.report'
    _description = 'MonthlyStockReport'

    # Filters fields, used for data computation

    location_id = fields.Many2one('stock.location', domain="[('usage','=','internal'),('company_id','=',company_id)]",
                                  string='Location',
                                  required=True)

    date_range_id = fields.Many2one('account.period', string='Date range', required=True)  #
    date_from = fields.Date('Start Date', required=True, default=fields.Date.today)
    date_to = fields.Date('End Date', required=True, default=fields.Date.today)

    refresh_report = fields.Boolean('Refresh Report')

    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id)

    line_product_ids = fields.One2many('stock.monthly.report.line', 'report_id')

    @api.model
    def default_get(self, fields_list):
        res = super(MonthlyStockReport, self).default_get(fields_list)

        today = fields.Date.context_today(self)
        today = fields.Date.from_string(today)

        from_date = (today + relativedelta(day=1, months=0, days=0))
        to_date = (today + relativedelta(day=1, months=1, days=-1))

        res['date_from'] = fields.Date.to_string(from_date)
        res['date_to'] = fields.Date.to_string(to_date)
        return res

    @api.onchange('date_range_id')
    def onchange_date_range_id(self):
        """Handle date range change."""
        if self.date_range_id:
            self.date_from = self.date_range_id.date_start
            self.date_to = self.date_range_id.date_stop

    @api.multi
    def do_fix_stock_move_location_from_picking(self):

        picking_type_out = self.env.ref('stock.picking_type_out')

        query = """
            SELECT sm.id
                FROM stock_move as sm  join stock_location as sl on sl.id = sm.location_id
                                       join stock_location as sld on sld.id = sm.location_dest_id       
                WHERE  
                    sm.state = 'done' AND
                    date >= %(date_from)s AND date  <= %(date_to)s  AND
                    picking_type_id  = %(picking_type_id)s
              GROUP BY sm.id 
        """
        params = {
            'location': self.location_id.id,
            'date_from': self.date_from + ' 00:00:00',
            'date_to': self.date_to + ' 23:59:59',
            'picking_type_id': picking_type_out.id
        }
        self.env.cr.execute(query, params=params)

        move_ids = []
        res = self.env.cr.fetchall()
        for row in res:
            move_ids += [row[0]]

        if move_ids:
            query = """
                 update stock_move set location_id = %(location)s
                 where id in %(move_ids)s
                """
            params = {
                'location': picking_type_out.default_location_src_id.id,
                'move_ids': tuple(move_ids)
            }

            self.env.cr.execute(query, params=params)

    @api.multi
    def do_fix_stock_move_location_source(self):
        picking_type_out = self.env.ref('stock.picking_type_out')

        # caut toate quanturile implicate in raport!
        query = """
        select sq.id
            from stock_quant as sq
                join stock_quant_move_rel as sqmr on sqmr.quant_id = sq.id 
                join stock_move as sm on sqmr.move_id = sm.id
            where
                 date >= %(date_from)s AND date  <= %(date_to)s AND
               ( sm.location_id = %(location)s OR sm.location_dest_id = %(location)s )       
            group by sq.id
        """
        params = {
            'location': self.location_id.id,
            'location_parent': self.location_id.location_id.id,
            'date_from': self.date_from + ' 00:00:00',
            'date_to': self.date_to + ' 23:59:59',
        }

        self.env.cr.execute(query, params=params)
        quant_ids = []
        res = self.env.cr.fetchall()
        for row in res:
            quant_ids += [row[0]]

        if quant_ids:

            # toate iesirile din stoc aferente acestui quant
            query = """
                select sm.id 
                    from stock_move as sm
                        join stock_quant_move_rel as sqmr   on sqmr.move_id = sm.id
                        where  sqmr.quant_id in %(quant_ids)s and 
                               picking_type_id  = %(picking_type_id)s and
                               sm.location_id = %(location_parent)s
            """
            params = {
                'quant_ids': tuple(quant_ids),

                'picking_type_id': picking_type_out.id,
                'location_parent': self.location_id.location_id.id,
            }
            self.env.cr.execute(query, params=params)
            move_ids = []
            res = self.env.cr.fetchall()
            for row in res:
                move_ids += [row[0]]

            if move_ids:
                query = """
                     update stock_move set location_id = %(location)s
                     where id in %(move_ids)s
                """
                params = {
                    'location': self.location_id.id,
                    'move_ids': tuple(move_ids)
                }

                self.env.cr.execute(query, params=params)

            # caut toate retururil
            query = """
                select sm.id 
                    from stock_move as sm
                        join stock_quant_move_rel as sqmr   on sqmr.move_id = sm.id
                        where  sqmr.quant_id in %(quant_ids)s and 
                              
                               sm.location_dest_id = %(location_parent)s
                """
            params = {
                'quant_ids': tuple(quant_ids),
                'picking_type_id': picking_type_out.id,
                'location_parent': self.location_id.location_id.id,
            }
            self.env.cr.execute(query, params=params)
            move_ids = []
            res = self.env.cr.fetchall()
            for row in res:
                move_ids += [row[0]]

            if move_ids:
                query = """
                 update stock_move set location_dest_id = %(location)s
                 where id in %(move_ids)s
                """
                params = {
                    'location': self.location_id.id,
                    'move_ids': tuple(move_ids)
                }

                self.env.cr.execute(query, params=params)

    @api.multi
    def do_execute(self):

        domain = [
            ('location_id', '=', self.location_id.id),
            ('date_from', '=', self.date_from),
            ('date_to', '=', self.date_to),
            ('id', '!=', self.id)
        ]
        if self.refresh_report:
            report = self.search(domain)
            report.unlink()
            report = False
        else:
            report = self.search(domain, limit=1)

        if not report:
            self.compute_data_for_report()
            report = self

        return report

    @api.multi
    def compute_data_for_report(self):

        self.do_fix_stock_move_location_source()

        stock_init = {}

        stock_in = {}

        stock_out = {}

        # determinare miscari pentru aceasta locatie care sunt pana la data de inceput
        query = """
            SELECT sm.product_id, 
                sum(CASE WHEN sm.location_id = %(location)s THEN -1*q.qty*q.cost
                    ELSE q.qty*q.cost
                    END), 
                sum(CASE WHEN sm.location_id = %(location)s THEN -1*q.qty
                    ELSE q.qty
                    END), 
                array_agg(sm.id) 
                
            FROM stock_move as sm
                LEFT JOIN stock_quant_move_rel ON  stock_quant_move_rel.move_id = sm.id
                LEFT JOIN stock_quant q ON  stock_quant_move_rel.quant_id = q.id
            WHERE  
                sm.state = 'done' AND
                sm.company_id = %(company)s AND 
                sm.date < %(date)s AND
              ( sm.location_id = %(location)s OR sm.location_dest_id = %(location)s)
             GROUP BY sm.product_id 
        """

        params = {
            'location': self.location_id.id,
            'company': self.company_id.id,
            'date': self.date_from + ' 00:00:00',
        }

        self.env.cr.execute(query, params=params)

        product_ids = []
        res = self.env.cr.fetchall()
        for row in res:
            product_ids += [row[0]]
            stock_init[row[0]] = {
                'report_id': self.id,
                'product_id': row[0],
                'amount_begin': row[1] or 0.0,
                'quantity_begin': row[2] or 0.0,
                'move_begin_ids': [(6, 0, list(row[3]))]
            }
        products = self.env['product.product'].browse(product_ids)

        # determinare care sunt intrari in stoc
        query = """
            SELECT sm.product_id, 
                sum(CASE WHEN sm.location_id = %(location)s THEN -1*q.qty*q.cost
                    ELSE q.qty*q.cost
                    END), 
                sum(CASE WHEN sm.location_id = %(location)s THEN -1*q.qty
                    ELSE q.qty
                    END), 
            array_agg(sm.id) 
            FROM stock_move as sm  join stock_location as sl on sl.id = sm.location_id
                                   join stock_location as sld on sld.id = sm.location_dest_id
                                   LEFT JOIN stock_quant_move_rel ON  stock_quant_move_rel.move_id = sm.id
                                   LEFT JOIN stock_quant q ON  stock_quant_move_rel.quant_id = q.id
            WHERE  
                sm.state = 'done' AND
                sm.company_id = %(company)s and 
                 date >= %(date_from)s AND date  <= %(date_to)s AND
               ( sm.location_id = %(location)s OR sm.location_dest_id = %(location)s ) and
              ( sld.usage not in ('customer','production') and sl.usage not in ('customer','production') )
             GROUP BY sm.product_id 
        """
        # and  sl.usage not in ('customer')
        params = {
            'location': self.location_id.id,
            'company': self.company_id.id,
            'date_from': self.date_from + ' 00:00:00',
            'date_to': self.date_to + ' 23:59:59',
        }

        self.env.cr.execute(query, params=params)

        product_ids = []
        res = self.env.cr.fetchall()
        for row in res:
            product_ids += [row[0]]
            stock_in[row[0]] = {
                'report_id': self.id,
                'product_id': row[0],
                'amount_in': row[1] or 0.0,
                'quantity_in': row[2] or 0.0,
                'move_in_ids': [(6, 0, list(row[3]))]
            }
        products |= self.env['product.product'].browse(product_ids)

        # determinare iesirile din aceasta locatie
        # se cosnidera iesire orice miscare care se duce intro locatie de client sau de productie
        query = """
                    SELECT sm.product_id, 
                        sum(CASE WHEN sm.location_id = %(location)s THEN 1*q.qty*q.cost
                            ELSE -1*q.qty*q.cost
                            END), 
                        sum(CASE WHEN sm.location_id = %(location)s THEN 1*q.qty
                            ELSE -q.qty
                            END), 
                    array_agg(sm.id) 
                    FROM stock_move as sm  join stock_location as sl on sl.id = sm.location_id
                                           join stock_location as sld on sld.id = sm.location_dest_id
                                           LEFT JOIN stock_quant_move_rel ON  stock_quant_move_rel.move_id = sm.id
                                            LEFT JOIN stock_quant q ON  stock_quant_move_rel.quant_id = q.id
                    WHERE  
                       sm.state = 'done' AND
                       sm.company_id = %(company)s and 
                         date >= %(date_from)s AND date  <= %(date_to)s AND
                       (sm.location_id = %(location)s OR sm.location_dest_id = %(location)s) and
                       not ( sld.usage not in ('customer','production') and sl.usage not in ('customer','production') ) 
                       
                     GROUP BY sm.product_id 
                """
        # or sl.usage  in ('customer')
        params = {
            'location': self.location_id.id,
            'company': self.company_id.id,
            'date_from': self.date_from + ' 00:00:00',
            'date_to': self.date_to + ' 23:59:59',
        }

        self.env.cr.execute(query, params=params)

        product_ids = []
        res = self.env.cr.fetchall()
        for row in res:
            product_ids += [row[0]]
            stock_out[row[0]] = {
                'report_id': self.id,
                'product_id': row[0],
                'amount_out': row[1] or 0.0,
                'quantity_out': row[2] or 0.0,
                'move_out_ids': [(6, 0, list(row[3]))]
            }
        products |= self.env['product.product'].browse(product_ids)

        for product in products:
            line_value = {
                'quantity_begin': 0.0,
                'quantity_in': 0.0,
                'quantity_out': 0.0,
                'categ_id': product.categ_id.id,
                'amount_begin': 0.0,
                'amount_in': 0.0,
                'amount_out': 0.0,
                'amount_sale': 0.0
            }

            init_product = stock_init.get(product.id, False)
            if init_product:
                line_value.update(init_product)

            in_product = stock_in.get(product.id, False)
            if in_product:
                line_value.update(in_product)
            out_product = stock_out.get(product.id, False)
            if out_product:
                line_value.update(out_product)
                # determinare pret de vanzare din liniile de comanda de vanzare:
                # move_line.procurement_id.sale_line_id
                moves = self.env['stock.move'].browse(out_product['move_out_ids'][0][2])
                for move_line in moves:
                    if move_line.procurement_id.sale_line_id:
                        line = move_line.procurement_id.sale_line_id

                        cur = line.order_id.pricelist_id.currency_id

                        taxes = line.tax_id.compute_all(line.price_unit, move_line.product_uom_qty, line.product_id,
                                                        line.order_id.partner_id)
                        amount_sale = cur.compute(taxes['total'], self.env.user.company_id.currency_id)
                        line_value['amount_sale'] += amount_sale

            line_value['quantity_finish'] = line_value['quantity_begin'] + line_value['quantity_in'] - line_value[
                'quantity_out']
            line_value['amount_finish'] = line_value['amount_begin'] + line_value['amount_in'] - line_value[
                'amount_out']
            if line_value['quantity_begin'] or line_value['quantity_in'] or line_value['quantity_out']:
                self.env['stock.monthly.report.line'].create(line_value)

    @api.multi
    def button_show(self):
        report = self.do_execute()
        # action = self.env.ref('deltatech_stock_report.action_monthly_stock_report_line').read()[0]
        # action['domain'] = [('report_id', '=', report.id)]
        # action['context'] = {'active_id': report.id}
        # action['target'] = 'main'
        # action['name'] = _('Monthly Stock %s') % report.date_range_id.name
        action = {
            'name': _('Monthly Stock %s') % report.date_range_id.name,
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'tree,graph',
            'context': {'active_id': report.id},
            'res_model': 'stock.monthly.report.line',
            'domain': [('report_id', '=', report.id)]
        }
        return action

    @api.multi
    def button_print(self):
        records = report = self.do_execute()
        report_name = 'deltatech_stock_report.action_report_monthly_stock_report'
        report = self.env.ref(report_name).report_action(records)
        return report


class MonthlyStockReportLine(models.TransientModel):
    _name = 'stock.monthly.report.line'
    _description = 'MonthlyStockReportLine'

    report_id = fields.Many2one('stock.monthly.report', string='Report')

    product_id = fields.Many2one('product.product', string='Product')
    categ_id = fields.Many2one('product.category', string='Category')

    quantity_begin = fields.Float('Quantity Begin')  # cantiatea la inceput de luna
    quantity_in = fields.Float('Quantity In')  # cantiatea intrata in aceasta luna
    quantity_out = fields.Float('Quantity Out')  # cantiatea iesita in aceasta luna
    quantity_finish = fields.Float('Quantity Finish')  # cantiatea la sfarsit de luna

    amount_begin = fields.Float('Amount Begin', help='Stock amount at the beginning of the period')
    amount_in = fields.Float('Amount In', help='Stock amount in of the period.')
    amount_out = fields.Float('Amount Out', help='Stock amount out of the period.')
    amount_sale = fields.Float('Amount of the sale', help='Amount of the sale')
    amount_finish = fields.Float('Amount Finish', help='Stock amount at end of period')

    move_begin_ids = fields.Many2many('stock.move', relation='stock_monthly_report_move_begin')
    move_in_ids = fields.Many2many('stock.move', relation='stock_monthly_report_move_in')
    move_out_ids = fields.Many2many('stock.move', relation='stock_monthly_report_move_out')

    @api.multi
    def action_move_begin_details(self):
        self.ensure_one()
        return self.show_move(self.move_begin_ids)

    @api.multi
    def action_move_in_details(self):
        self.ensure_one()
        return self.show_move(self.move_in_ids)

    @api.multi
    def action_move_out_details(self):
        self.ensure_one()
        return self.show_move(self.move_out_ids)

    @api.multi
    def show_move(self, move_ids):
        action = {
            'name': _('Move'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'tree,form',
            'context': self.env.context,
            'res_model': 'stock.move',
            'domain': [('id', 'in', move_ids.ids)]
        }

        tree_view_ref = self.env.ref('stock.view_move_tree')
        # form_view_ref = self.env.ref('account.view_move_line_form')
        action['views'] = [(tree_view_ref.id, 'tree')] #, (form_view_ref.id, 'form')]

        return action
