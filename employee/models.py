from django.db import models
from django.contrib.auth.models import User

class ShopLocation(models.Model):
    name = models.CharField(max_length=255, unique=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['-created_at']

class ShopEmployee(models.Model):
    shop_location = models.ForeignKey(ShopLocation, on_delete=models.CASCADE, related_name='employees')
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['shop_location', 'employee']
    
    def __str__(self):
        return f"{self.employee.username} - {self.shop_location.name}"

class Stock(models.Model):
    shop_location = models.ForeignKey(ShopLocation, on_delete=models.CASCADE, related_name='stock_items')
    item_name = models.CharField(max_length=255)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.item_name} - {self.shop_location.name}"
    
    class Meta:
        ordering = ['-created_at']

class Sale(models.Model):
    shop_location = models.ForeignKey(ShopLocation, on_delete=models.CASCADE, related_name='sales')
    employee = models.ForeignKey(User, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=255)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    sale_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.item_name} - {self.shop_location.name} ({self.sale_date})"
    
    class Meta:
        ordering = ['-sale_date']
