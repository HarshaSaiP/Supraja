"""
URL configuration for Supraja project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from login.views import (login_view, admin_dashboard, create_admin_view, create_employee_view, 
                        employee_dashboard, logout_view, add_stock_view, check_stock_view,
                        create_shop_location_view, shop_locations_view, assign_employee_to_shop_view,
                        remove_employee_from_shop_view, employee_shop_stock_view, admin_sales_view,
                        admin_get_sales_data, delete_employee, delete_stock_view, delete_shop_location_view,
                        farmer_search_view, admin_farmers_view, clear_farmer_due_view, farmer_due_pdf_view)
from admin.views import gstr1_download_view, search_product_names
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('', login_view, name='home'),
    path('admin-dashboard/', admin_dashboard, name='admin_dashboard'),
    path('create-admin/', create_admin_view, name='create_admin'),
    path('create-employee/', create_employee_view, name='create_employee'),
    path('employee-dashboard/', employee_dashboard, name='employee_dashboard'),
    path('add-stock/', add_stock_view, name='add_stock'),
    path('check-stock/', check_stock_view, name='check_stock'),
    path('create-shop-location/', create_shop_location_view, name='create_shop_location'),
    path('shop-locations/', shop_locations_view, name='shop_locations'),
    path('assign-employee/<int:shop_id>/', assign_employee_to_shop_view, name='assign_employee_to_shop'),
    path('remove-employee/<int:assignment_id>/', remove_employee_from_shop_view, name='remove_employee_from_shop'),
    path('employee-shop-stock/', employee_shop_stock_view, name='employee_shop_stock'),
    path('admin-sales/', admin_sales_view, name='admin_sales'),
    path('admin-get-sales-data/', admin_get_sales_data, name='admin_get_sales_data'),
    path('delete-employee/<int:user_id>/', delete_employee, name='delete_employee'),
    path('delete-stock/<int:stock_id>/', delete_stock_view, name='delete_stock'),
    path('delete-shop-location/<int:shop_id>/', delete_shop_location_view, name='delete_shop_location'),
    path('admin-farmers/', admin_farmers_view, name='admin_farmers'),
    path('clear-farmer-due/', clear_farmer_due_view, name='clear_farmer_due'),
    path('farmer-due-pdf/<int:farmer_id>/', farmer_due_pdf_view, name='farmer_due_pdf'),
    path('all-farmers-due-pdf/', farmer_due_pdf_view, {'farmer_id': None}, name='all_farmers_due_pdf'),
    path('gstr1-download/', gstr1_download_view, name='gstr1_download'),
    path('search-product-names/', search_product_names, name='search_product_names'),
    path('farmer-search/', farmer_search_view, name='farmer_search'),
] + static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
