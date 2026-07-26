from django.contrib import admin
from .models import ShopLocation, ShopEmployee, Stock

@admin.register(ShopLocation)
class ShopLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'created_at')
    search_fields = ('name',)

@admin.register(ShopEmployee)
class ShopEmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee', 'shop_location', 'assigned_at')
    search_fields = ('employee__username', 'shop_location__name')
    list_filter = ('shop_location', 'assigned_at')

@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'shop_location', 'quantity', 'price', 'updated_at')
    search_fields = ('item_name', 'shop_location__name')
    list_filter = ('shop_location', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
