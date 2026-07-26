from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from datetime import datetime, date
from django.db.models import Sum, F, Q
from decimal import Decimal
from employee.models import Sale, ShopLocation, Stock
from .forms import GSTR1FilterForm
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from io import BytesIO


@login_required(login_url='login')
def gstr1_download_view(request):
    """View to handle GSTR-1 download with date filtering"""
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    form = GSTR1FilterForm()
    
    if request.method == 'POST':
        form = GSTR1FilterForm(request.POST)
        if form.is_valid():
            from_month = int(form.cleaned_data['from_month'])
            from_year = int(form.cleaned_data['from_year'])
            to_month = int(form.cleaned_data['to_month'])
            to_year = int(form.cleaned_data['to_year'])
            
            # Validate date range
            from_date = date(from_year, from_month, 1)
            # Get last day of to_month
            if to_month == 12:
                to_date = date(to_year + 1, 1, 1)
            else:
                to_date = date(to_year, to_month + 1, 1)
            
            if from_date > to_date:
                form.add_error(None, "From date must be before To date")
                return render(request, 'admin/gstr1_download.html', {'form': form})
            
            # Query sales data within the date range, excluding 0% GST items
            sales = Sale.objects.filter(
                sale_date__gte=from_date,
                sale_date__lt=to_date,
                gst_percent__gt=0
            ).select_related('shop_location', 'employee').order_by('sale_date')
            
            # Generate Excel file
            excel_file = generate_gstr1_excel(sales, from_month, from_year, to_month, to_year)
            
            # Create HTTP response
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="GSTR1_{from_month}_{from_year}_to_{to_month}_{to_year}.xlsx"'
            response.write(excel_file.getvalue())
            return response
    
    return render(request, 'admin/gstr1_download.html', {'form': form})


def generate_gstr1_excel(sales, from_month, from_year, to_month, to_year):
    """Generate GSTR-1 Excel file from sales data"""
    
    # Create workbook and select active sheet
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "GSTR-1"
    
    # Define styles
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    subheader_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    subheader_font = Font(bold=True, size=11)
    summary_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    summary_font = Font(bold=True, size=11)
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Set column widths
    worksheet.column_dimensions['A'].width = 12
    worksheet.column_dimensions['B'].width = 20
    worksheet.column_dimensions['C'].width = 25
    worksheet.column_dimensions['D'].width = 12
    worksheet.column_dimensions['E'].width = 12
    worksheet.column_dimensions['F'].width = 12
    worksheet.column_dimensions['G'].width = 12
    worksheet.column_dimensions['H'].width = 12
    worksheet.column_dimensions['I'].width = 10
    worksheet.column_dimensions['J'].width = 10
    worksheet.column_dimensions['K'].width = 13
    worksheet.column_dimensions['L'].width = 13
    worksheet.column_dimensions['M'].width = 15
    
    # Title
    worksheet['A1'] = "GSTR-1 Report"
    worksheet['A1'].font = Font(bold=True, size=14)
    worksheet.merge_cells('A1:M1')
    
    # Date range
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    date_range_text = f"Period: {month_names[from_month-1]} {from_year} to {month_names[to_month-1]} {to_year}"
    worksheet['A2'] = date_range_text
    worksheet['A2'].font = Font(italic=True, size=10)
    worksheet.merge_cells('A2:M2')
    
    # Generated on
    worksheet['A3'] = f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
    worksheet['A3'].font = Font(italic=True, size=9)
    worksheet.merge_cells('A3:M3')
    
    # Headers
    headers = ['Sale Date', 'Shop Location', 'Item Name', 'HSN Code', 'Batch Number', 'Quantity', 'Unit Price', 'Discount %', 'SGST %', 'CGST %', 'SGST Amount', 'CGST Amount', 'Total Amount']
    for col_num, header in enumerate(headers, 1):
        cell = worksheet.cell(row=5, column=col_num)
        cell.value = header
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border
    
    # Data rows
    row = 6
    total_quantity = 0
    total_sgst_amount = Decimal('0.00')
    total_cgst_amount = Decimal('0.00')
    total_amount = Decimal('0.00')
    
    for sale in sales:
        # Calculate SGST and CGST (each is half of total GST)
        sgst_percent = sale.gst_percent / 2
        cgst_percent = sale.gst_percent / 2
        sgst_amount = sale.gst_amount / 2
        cgst_amount = sale.gst_amount / 2
        
        worksheet.cell(row=row, column=1).value = sale.sale_date.strftime('%d-%m-%Y')
        worksheet.cell(row=row, column=2).value = sale.shop_location.name
        worksheet.cell(row=row, column=3).value = sale.item_name
        worksheet.cell(row=row, column=4).value = sale.hsn_code if sale.hsn_code else ''
        worksheet.cell(row=row, column=5).value = sale.batch_number if sale.batch_number else ''
        worksheet.cell(row=row, column=6).value = sale.quantity
        worksheet.cell(row=row, column=7).value = float(sale.unit_price)
        worksheet.cell(row=row, column=8).value = float(sale.discount_percent)
        worksheet.cell(row=row, column=9).value = float(sgst_percent)
        worksheet.cell(row=row, column=10).value = float(cgst_percent)
        worksheet.cell(row=row, column=11).value = float(sgst_amount)
        worksheet.cell(row=row, column=12).value = float(cgst_amount)
        worksheet.cell(row=row, column=13).value = float(sale.total_amount)
        
        # Apply borders and formatting
        for col in range(1, 14):
            cell = worksheet.cell(row=row, column=col)
            cell.border = border
            if col in [6, 7, 8, 9, 10, 11, 12, 13]:
                cell.alignment = Alignment(horizontal='right')
            if col in [7, 8, 9, 10, 11, 12, 13]:
                cell.number_format = '0.00'
        
        total_quantity += sale.quantity
        total_sgst_amount += sgst_amount
        total_cgst_amount += cgst_amount
        total_amount += sale.total_amount
        row += 1
    
    # Summary row
    summary_row = row + 1
    worksheet.cell(row=summary_row, column=1).value = "TOTAL"
    worksheet.cell(row=summary_row, column=1).font = summary_font
    worksheet.cell(row=summary_row, column=1).fill = summary_fill
    
    worksheet.cell(row=summary_row, column=6).value = total_quantity
    worksheet.cell(row=summary_row, column=6).font = summary_font
    worksheet.cell(row=summary_row, column=6).fill = summary_fill
    worksheet.cell(row=summary_row, column=6).border = border
    
    worksheet.cell(row=summary_row, column=11).value = float(total_sgst_amount)
    worksheet.cell(row=summary_row, column=11).font = summary_font
    worksheet.cell(row=summary_row, column=11).fill = summary_fill
    worksheet.cell(row=summary_row, column=11).number_format = '0.00'
    worksheet.cell(row=summary_row, column=11).border = border
    
    worksheet.cell(row=summary_row, column=12).value = float(total_cgst_amount)
    worksheet.cell(row=summary_row, column=12).font = summary_font
    worksheet.cell(row=summary_row, column=12).fill = summary_fill
    worksheet.cell(row=summary_row, column=12).number_format = '0.00'
    worksheet.cell(row=summary_row, column=12).border = border
    
    worksheet.cell(row=summary_row, column=13).value = float(total_amount)
    worksheet.cell(row=summary_row, column=13).font = summary_font
    worksheet.cell(row=summary_row, column=13).fill = summary_fill
    worksheet.cell(row=summary_row, column=13).number_format = '0.00'
    worksheet.cell(row=summary_row, column=13).border = border
    
    # Apply borders to all cells in summary row
    for col in range(1, 14):
        cell = worksheet.cell(row=summary_row, column=col)
        cell.border = border
    
    # Save to BytesIO
    excel_buffer = BytesIO()
    workbook.save(excel_buffer)
    excel_buffer.seek(0)
    
    return excel_buffer


@login_required(login_url='login')
def search_product_names(request):
    """API endpoint to search for similar product names"""
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'products': []})
    
    # Search for products with similar names in Stock
    products = Stock.objects.filter(
        item_name__icontains=query
    ).values_list('item_name', flat=True).distinct().order_by('item_name')[:10]
    
    return JsonResponse({'products': list(products)})
