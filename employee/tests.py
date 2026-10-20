from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from employee.models import Sale, ShopEmployee, ShopLocation, Stock, Farmer


class EmployeeSaleConfirmationValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='employee1', password='secret123')
        self.shop = ShopLocation.objects.create(name='Main Shop', address='Address 1')
        ShopEmployee.objects.create(shop_location=self.shop, employee=self.user)
        self.stock = Stock.objects.create(
            shop_location=self.shop,
            item_name='Rice Bag',
            quantity=10,
            price=Decimal('125.00'),
            gst_percent=Decimal('5.00'),
        )

    def _set_pending_sale(self, amount_paid):
        session = self.client.session
        session['pending_sale'] = {
            'shop_id': self.shop.id,
            'lines': [
                {'stock_id': self.stock.id, 'quantity': 1, 'discount_percent': 0}
            ],
        }
        session.save()
        self.client.force_login(self.user)
        return self.client.post(
            '/employee-dashboard/',
            {
                'action': 'confirm_sale',
                'farmer_name': 'Ravi Kumar',
                'farmer_phone': '9876543210',
                'amount_paid': amount_paid,
            },
        )

    def test_zero_amount_paid_is_allowed(self):
        response = self._set_pending_sale('0')

        self.assertEqual(response.status_code, 200)
        self.assertIn('success', response.context)
        self.assertIn('Amount Paid: Rs. 0.00', response.context['success'])

    def test_negative_amount_paid_is_rejected(self):
        response = self._set_pending_sale('-1')

        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.context)
        self.assertIn('cannot be negative', response.context['error'].lower())

    def test_amount_paid_cannot_exceed_bill_total(self):
        response = self._set_pending_sale('5000')

        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.context)
        self.assertIn('cannot exceed the bill total', response.context['error'].lower())


class FarmerDuePdfExportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='secret123')
        self.shop = ShopLocation.objects.create(name='Main Shop', address='Address 1')
        self.farmer = Farmer.objects.create(name='Ravi Kumar', phone='9876543210')
        self.stock = Stock.objects.create(
            shop_location=self.shop,
            item_name='Rice Bag',
            quantity=10,
            price=Decimal('125.00'),
            gst_percent=Decimal('5.00'),
        )
        Sale.objects.create(
            shop_location=self.shop,
            employee=self.admin,
            farmer=self.farmer,
            farmer_name='Ravi Kumar',
            farmer_phone='9876543210',
            amount_paid=Decimal('0.00'),
            item_name='Rice Bag',
            quantity=1,
            unit_price=Decimal('125.00'),
            discount_percent=Decimal('0.00'),
            gst_percent=Decimal('5.00'),
            gst_amount=Decimal('6.25'),
            total_amount=Decimal('131.25'),
        )
        self.client.force_login(self.admin)

    def test_farmer_due_pdf_is_generated(self):
        url = reverse('farmer_due_pdf', args=[self.farmer.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn(b'Ravi Kumar', response.content)
        self.assertIn(b'9876543210', response.content)
        self.assertIn(b'131.25', response.content)


class AdminBillPdfExportTests(TestCase):
    def test_admin_can_download_itemized_bill(self):
        admin = User.objects.create_superuser(username='billadmin', email='admin@example.com', password='secret123')
        shop = ShopLocation.objects.create(name='Main Shop', address='Address 1')
        bill_id = 'b6f4c3f1-7e18-45b4-83e7-4e3d8bb8a1c5'
        Sale.objects.create(
            bill_id=bill_id, shop_location=shop, employee=admin,
            farmer_name='Ravi Kumar', farmer_phone='9876543210',
            amount_paid=Decimal('50.00'), item_name='Rice Bag', quantity=1,
            unit_price=Decimal('125.00'), discount_percent=Decimal('0.00'),
            gst_percent=Decimal('5.00'), gst_amount=Decimal('6.25'),
            total_amount=Decimal('131.25'),
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('admin_bill_pdf', args=[bill_id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))
