from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.conf import settings
import uuid
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from datetime import date
from employee.models import ShopLocation, ShopEmployee, Stock, Sale, Farmer

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError:  # pragma: no cover
    colors = None
    A4 = None
    getSampleStyleSheet = None
    mm = None
    Image = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None

def normalize_stock_for_shop(shop_location):
    shop_stock = Stock.objects.filter(shop_location=shop_location).order_by('-updated_at', '-id')
    grouped_stock = {}

    for stock_item in shop_stock:
        item_key = stock_item.item_name.strip().lower()
        if item_key not in grouped_stock:
            grouped_stock[item_key] = {
                'primary': stock_item,
                'duplicates': [],
            }
        else:
            grouped_stock[item_key]['duplicates'].append(stock_item)

    for group in grouped_stock.values():
        duplicates = group['duplicates']
        if not duplicates:
            continue

        primary = group['primary']
        primary.quantity += sum(item.quantity for item in duplicates)
        primary.save()
        Stock.objects.filter(id__in=[item.id for item in duplicates]).delete()

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect to admin dashboard if admin
            if user.is_superuser:
                return redirect('admin_dashboard')
            else:
                return redirect('employee_dashboard')
        else:
            error = "Invalid credentials"
            return render(request, 'login/login.html', {'error': error})
    
    return render(request, 'login/login.html')

def home_view(request):
    return render(request, 'home.html')

@login_required(login_url='login')
def admin_dashboard(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    admins = User.objects.filter(is_superuser=True)
    employees = User.objects.filter(is_superuser=False, is_staff=False)
    employee_assignments = ShopEmployee.objects.select_related('shop_location', 'employee')

    locations_by_employee_id = {}
    for assignment in employee_assignments:
        employee_id = assignment.employee_id
        if employee_id not in locations_by_employee_id:
            locations_by_employee_id[employee_id] = []
        locations_by_employee_id[employee_id].append(assignment.shop_location.name)

    employee_rows = []
    for employee in employees:
        assigned_locations = locations_by_employee_id.get(employee.id, [])
        employee_rows.append({
            'employee': employee,
            'assigned_locations': ", ".join(assigned_locations) if assigned_locations else "Not assigned",
        })
    
    # Best seller item by total quantity sold
    from django.db.models import Sum
    best_seller = (
        Sale.objects
        .values('item_name')
        .annotate(total_qty=Sum('quantity'))
        .order_by('-total_qty')
        .first()
    )
    
    # Best customer by total money spent
    best_customer = (
        Sale.objects
        .exclude(farmer_name__isnull=True)
        .exclude(farmer_name='')
        .values('farmer_name')
        .annotate(total_spent=Sum('total_amount'))
        .order_by('-total_spent')
        .first()
    )
    
    # Items expiring in less than 10 days
    from datetime import timedelta
    expiry_cutoff = date.today() + timedelta(days=10)
    expiring_items = Stock.objects.filter(
        exp_date__isnull=False,
        exp_date__lte=expiry_cutoff,
        exp_date__gte=date.today()
    ).select_related('shop_location').order_by('exp_date')
    
    return render(request, 'admin/dashboard.html', {
        'admin_name': request.user.username,
        'admins': admins,
        'employees': employees,
        'employee_rows': employee_rows,
        'best_seller': best_seller,
        'best_customer': best_customer,
        'expiring_items': expiring_items,
    })

@login_required(login_url='login')
def create_admin_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        email = request.POST.get('email', '')
        
        if User.objects.filter(username=username).exists():
            error = "Username already exists"
            return render(request, 'admin/create_admin.html', {'error': error})
        
        User.objects.create_superuser(username, email, password)
        return redirect('admin_dashboard')
    
    return render(request, 'admin/create_admin.html')

@login_required(login_url='login')
def create_employee_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        email = request.POST.get('email', '')
        
        if User.objects.filter(username=username).exists():
            error = "Username already exists"
            return render(request, 'admin/create_employee.html', {'error': error})
        
        User.objects.create_user(username, email, password)
        return redirect('admin_dashboard')
    
    return render(request, 'admin/create_employee.html')

@login_required(login_url='login')
def employee_dashboard(request):
    assigned_shops = ShopLocation.objects.filter(
        employees__employee=request.user
    ).distinct()
    primary_assigned_shop = assigned_shops.first()
    pending_sale = request.session.get('pending_sale')
    
    # Items expiring in less than 10 days for assigned shops
    from datetime import timedelta
    expiry_cutoff = date.today() + timedelta(days=10)
    expiring_items = Stock.objects.filter(
        shop_location__in=assigned_shops,
        exp_date__isnull=False,
        exp_date__lte=expiry_cutoff,
        exp_date__gte=date.today()
    ).select_related('shop_location').order_by('exp_date')

    if request.method == 'POST':
        if request.POST.get('action') == 'cancel_sale':
            request.session.pop('pending_sale', None)
            return render(request, 'employee/dashboard.html', {
                'employee_name': request.user.username,
                'assigned_shops': assigned_shops,
                'primary_assigned_shop': primary_assigned_shop,
                'expiring_items': expiring_items,
            })

        if request.POST.get('action') == 'confirm_sale':
            if not pending_sale:
                error = "No pending sale found. Please create the sale again."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            # Get farmer details from the form
            farmer_name = request.POST.get('farmer_name', '').strip()
            farmer_phone = request.POST.get('farmer_phone', '').strip()
            amount_paid_raw = request.POST.get('amount_paid', '').strip()

            if not farmer_name or not farmer_phone or not amount_paid_raw:
                error = "Please fill in Farmer Name, Farmer Phone Number, and Amount Paid."
                # Re-build preview lines for the modal
                preview_lines = []
                preview_total = Decimal('0.00')
                for line in pending_sale.get('lines', []):
                    stock_item = Stock.objects.filter(id=line['stock_id']).first()
                    if not stock_item:
                        continue
                    dp = Decimal(str(line['discount_percent']))
                    qty = int(line['quantity'])
                    sub = stock_item.price * qty
                    da = (sub * dp) / Decimal('100')
                    pad = sub - da
                    ga = (pad * stock_item.gst_percent) / Decimal('100')
                    lt = pad + ga
                    preview_lines.append({
                        'item_name': stock_item.item_name,
                        'unit_price': stock_item.price,
                        'quantity': qty,
                        'discount_percent': dp,
                        'gst_percent': stock_item.gst_percent,
                        'gst_amount': ga,
                        'line_total': lt,
                    })
                    preview_total += lt
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'pending_sale_lines': preview_lines,
                    'pending_sale_total': f"{preview_total:.2f}",
                    'expiring_items': expiring_items,
                })

            try:
                amount_paid = Decimal(amount_paid_raw)
            except (InvalidOperation, ValueError):
                error = "Invalid amount paid. Please enter a valid number."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            if not amount_paid.is_finite() or amount_paid < 0:
                error = "Amount paid cannot be negative or invalid."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            # Validate phone: must be exactly 10 digits and not all same digits
            phone_digits = ''.join(c for c in farmer_phone if c.isdigit())
            if len(phone_digits) != 10:
                error = "Farmer phone number must be exactly 10 digits."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })
            elif len(set(phone_digits)) == 1:
                error = "Farmer phone number cannot be all the same digits."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            # Calculate the bill total to validate amount_paid
            bill_total = Decimal('0.00')
            for line in pending_sale.get('lines', []):
                stock_item = Stock.objects.filter(id=line['stock_id']).first()
                if not stock_item:
                    continue
                dp = Decimal(str(line['discount_percent']))
                qty = int(line['quantity'])
                sub = stock_item.price * qty
                da = (sub * dp) / Decimal('100')
                pad = sub - da
                ga = (pad * stock_item.gst_percent) / Decimal('100')
                bill_total += pad + ga

            if amount_paid > bill_total:
                error = f"Amount paid (Rs. {amount_paid:.2f}) cannot exceed the bill total (Rs. {bill_total:.2f})."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            # Get or create the Farmer record
            farmer, _created = Farmer.objects.get_or_create(
                name__iexact=farmer_name,
                phone=farmer_phone,
                defaults={'name': farmer_name, 'phone': farmer_phone}
            )
            # Update name casing if needed
            if not _created and farmer.name != farmer_name:
                farmer.name = farmer_name
                farmer.save()

            total_final_price = Decimal('0.00')
            bill_id = uuid.uuid4()
            try:
                with transaction.atomic():
                    required_quantity_by_stock = {}
                    for line in pending_sale.get('lines', []):
                        stock_id = int(line['stock_id'])
                        required_quantity_by_stock[stock_id] = required_quantity_by_stock.get(stock_id, 0) + int(line['quantity'])

                    locked_stocks = {
                        stock.id: stock
                        for stock in Stock.objects.select_for_update().filter(
                            id__in=list(required_quantity_by_stock.keys()),
                            shop_location_id=pending_sale['shop_id']
                        )
                    }

                    for stock_id, required_quantity in required_quantity_by_stock.items():
                        stock_item = locked_stocks.get(stock_id)
                        if not stock_item:
                            raise ValueError("Invalid stock item selected.")
                        if stock_item.quantity < required_quantity:
                            raise ValueError(f"Not enough stock for {stock_item.item_name}. Available: {stock_item.quantity}")

                    for line in pending_sale.get('lines', []):
                        stock_item = locked_stocks[int(line['stock_id'])]
                        sell_quantity = int(line['quantity'])
                        discount_percent = Decimal(str(line['discount_percent']))
                        if discount_percent < 0 or discount_percent > 100:
                            raise ValueError(f"Discount percentage must be between 0 and 100 for {stock_item.item_name}.")

                        subtotal = stock_item.price * sell_quantity
                        discount_amount = (subtotal * discount_percent) / Decimal('100')
                        price_after_discount = subtotal - discount_amount
                        gst_amount = (price_after_discount * stock_item.gst_percent) / Decimal('100')
                        line_total = price_after_discount + gst_amount
                        
                        if line_total < 0:
                            raise ValueError(f"Invalid total for {stock_item.item_name}.")

                        stock_item.quantity -= sell_quantity
                        stock_item.save()
                        total_final_price += line_total
                        Sale.objects.create(
                            bill_id=bill_id,
                            shop_location_id=pending_sale['shop_id'],
                            employee=request.user,
                            farmer=farmer,
                            farmer_name=farmer_name,
                            farmer_phone=farmer_phone,
                            amount_paid=amount_paid,
                            item_name=stock_item.item_name,
                            hsn_code=stock_item.hsn_code,
                            batch_number=stock_item.batch_number,
                            quantity=sell_quantity,
                            unit_price=stock_item.price,
                            discount_percent=discount_percent,
                            gst_percent=stock_item.gst_percent,
                            gst_amount=gst_amount,
                            total_amount=line_total
                        )
            except (Stock.DoesNotExist, ValueError, InvalidOperation) as exc:
                error = str(exc) if str(exc) else "Could not complete the sale."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            # Sale successful — clear session and show success
            request.session.pop('pending_sale', None)
            success = f"Sale confirmed successfully! Total: Rs. {total_final_price:.2f} | Farmer: {farmer_name} | Amount Paid: Rs. {amount_paid:.2f}"
            return render(request, 'employee/dashboard.html', {
                'employee_name': request.user.username,
                'assigned_shops': assigned_shops,
                'primary_assigned_shop': primary_assigned_shop,
                'success': success,
                'expiring_items': expiring_items,
            })

        stock_ids = request.POST.getlist('stock_id[]')
        quantities = request.POST.getlist('quantity[]')
        discounts = request.POST.getlist('discount_percent[]')

        if not primary_assigned_shop:
            error = "No shop location is assigned to you."
            return render(request, 'employee/dashboard.html', {
                'employee_name': request.user.username,
                'assigned_shops': assigned_shops,
                'primary_assigned_shop': primary_assigned_shop,
                'error': error,
                'expiring_items': expiring_items,
            })

        sale_lines = []
        for index, stock_id in enumerate(stock_ids):
            stock_id = stock_id.strip()
            if not stock_id:
                continue

            quantity_raw = quantities[index].strip() if index < len(quantities) else ""
            discount_raw = discounts[index].strip() if index < len(discounts) else "0"

            try:
                quantity = int(quantity_raw)
                discount_percent = Decimal(discount_raw or "0")
                if quantity <= 0:
                    raise ValueError
                if discount_percent < 0 or discount_percent > 100:
                    raise ValueError
            except (ValueError, InvalidOperation):
                error = "Invalid quantity or discount percentage entered."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            try:
                stock_item = Stock.objects.get(id=stock_id, shop_location=primary_assigned_shop)
            except Stock.DoesNotExist:
                error = "Invalid stock item selected."
                return render(request, 'employee/dashboard.html', {
                    'employee_name': request.user.username,
                    'assigned_shops': assigned_shops,
                    'primary_assigned_shop': primary_assigned_shop,
                    'error': error,
                    'expiring_items': expiring_items,
                })

            sale_lines.append({
                'stock': stock_item,
                'quantity': quantity,
                'discount_percent': discount_percent,
            })

        if not sale_lines:
            error = "Add at least one item to sell."
            return render(request, 'employee/dashboard.html', {
                'employee_name': request.user.username,
                'assigned_shops': assigned_shops,
                'primary_assigned_shop': primary_assigned_shop,
                'error': error,
                'expiring_items': expiring_items,
            })

        preview_lines = []
        preview_total = Decimal('0.00')
        try:
            for line in sale_lines:
                stock_item = Stock.objects.get(id=line['stock'].id)
                sell_quantity = line['quantity']
                if stock_item.quantity < sell_quantity:
                    raise ValueError(f"Not enough stock for {stock_item.item_name}. Available: {stock_item.quantity}")

                if line['discount_percent'] > 100:
                    raise ValueError(f"Discount percentage is too high for {stock_item.item_name}.")

                subtotal = stock_item.price * sell_quantity
                discount_amount = (subtotal * line['discount_percent']) / Decimal('100')
                price_after_discount = subtotal - discount_amount
                gst_amount = (price_after_discount * stock_item.gst_percent) / Decimal('100')
                line_total = price_after_discount + gst_amount

                preview_lines.append({
                    'item_name': stock_item.item_name,
                    'unit_price': stock_item.price,
                    'quantity': sell_quantity,
                    'discount_percent': line['discount_percent'],
                    'gst_percent': stock_item.gst_percent,
                    'gst_amount': gst_amount,
                    'line_total': line_total,
                    'stock_id': stock_item.id,
                })
                preview_total += line_total
        except ValueError as exc:
            return render(request, 'employee/dashboard.html', {
                'employee_name': request.user.username,
                'assigned_shops': assigned_shops,
                'primary_assigned_shop': primary_assigned_shop,
                'error': str(exc),
                'expiring_items': expiring_items,
            })

        request.session['pending_sale'] = {
            'shop_id': primary_assigned_shop.id,
            'lines': [
                {
                    'stock_id': line['stock_id'],
                    'quantity': line['quantity'],
                    'discount_percent': str(line['discount_percent']),
                }
                for line in preview_lines
            ],
        }
        preview_total_str = f"{preview_total:.2f}"
        return render(request, 'employee/dashboard.html', {
            'employee_name': request.user.username,
            'assigned_shops': assigned_shops,
            'primary_assigned_shop': primary_assigned_shop,
            'pending_sale_lines': preview_lines,
            'pending_sale_total': preview_total_str,
            'expiring_items': expiring_items,
        })

    pending_sale_lines = []
    pending_sale_total = None
    if pending_sale:
        try:
            preview_total = Decimal('0.00')
            for line in pending_sale.get('lines', []):
                stock_item = Stock.objects.filter(id=line['stock_id']).first()
                if not stock_item:
                    continue
                discount_percent = Decimal(str(line['discount_percent']))
                quantity = int(line['quantity'])
                subtotal = stock_item.price * quantity
                discount_amount = (subtotal * discount_percent) / Decimal('100')
                price_after_discount = subtotal - discount_amount
                gst_amount = (price_after_discount * stock_item.gst_percent) / Decimal('100')
                line_total = price_after_discount + gst_amount

                pending_sale_lines.append({
                    'item_name': stock_item.item_name,
                    'unit_price': stock_item.price,
                    'quantity': quantity,
                    'discount_percent': discount_percent,
                    'gst_percent': stock_item.gst_percent,
                    'gst_amount': gst_amount,
                    'line_total': line_total,
                })
                preview_total += line_total
            pending_sale_total = f"{preview_total:.2f}" if pending_sale_lines else None
        except (InvalidOperation, ValueError, TypeError):
            request.session.pop('pending_sale', None)

    return render(request, 'employee/dashboard.html', {
        'employee_name': request.user.username,
        'assigned_shops': assigned_shops,
        'primary_assigned_shop': primary_assigned_shop,
        'pending_sale_lines': pending_sale_lines,
        'pending_sale_total': pending_sale_total,
        'expiring_items': expiring_items,
    })

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required(login_url='login')
def add_stock_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    if request.method == 'POST':
        shop_location_id = request.POST.get('shop_location')
        item_name = request.POST.get('item_name')
        hsn_code = request.POST.get('hsn_code', '').strip()
        batch_number = request.POST.get('batch_number', '').strip()
        manufacturing_date_str = request.POST.get('manufacturing_date', '').strip()
        exp_date_str = request.POST.get('exp_date', '').strip()
        quantity = request.POST.get('quantity')
        price = request.POST.get('price')
        gst_percent = request.POST.get('gst_percent', '0')
        
        # Parse DD/MM/YYYY date format
        manufacturing_date = None
        exp_date = None
        try:
            if manufacturing_date_str:
                parts = manufacturing_date_str.split('/')
                if len(parts) == 3:
                    manufacturing_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
            if exp_date_str:
                parts = exp_date_str.split('/')
                if len(parts) == 3:
                    exp_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            error = "Invalid date format. Please use DD/MM/YYYY"
            shop_locations = ShopLocation.objects.all()
            return render(request, 'admin/add_stock.html', {'error': error, 'shop_locations': shop_locations})
        
        if not item_name or not quantity or not price:
            error = "Item name, quantity, and price are required"
            shop_locations = ShopLocation.objects.all()
            return render(request, 'admin/add_stock.html', {'error': error, 'shop_locations': shop_locations})
        
        try:
            if not shop_location_id:
                error = "Please select a shop location"
                shop_locations = ShopLocation.objects.all()
                return render(request, 'admin/add_stock.html', {'error': error, 'shop_locations': shop_locations})
            
            shop_location = ShopLocation.objects.get(id=shop_location_id)
            normalized_item_name = item_name.strip()
            quantity_to_add = int(quantity)
            unit_price = Decimal(price)

            # Search for matching stocks based on item name, batch number, and manufacturing date
            matching_stocks = Stock.objects.filter(
                shop_location=shop_location,
                item_name__iexact=normalized_item_name,
                batch_number=batch_number if batch_number else None,
                manufacturing_date=manufacturing_date if manufacturing_date else None
            ).order_by('-updated_at', '-id')

            if matching_stocks.exists():
                # Merge with existing stock
                primary_stock = matching_stocks.first()
                duplicate_stocks = list(matching_stocks[1:])
                duplicate_quantity = sum(stock.quantity for stock in duplicate_stocks)

                primary_stock.quantity += quantity_to_add + duplicate_quantity
                primary_stock.price = unit_price
                primary_stock.gst_percent = Decimal(gst_percent)
                if hsn_code:
                    primary_stock.hsn_code = hsn_code
                if exp_date:
                    primary_stock.exp_date = exp_date
                primary_stock.save()

                if duplicate_stocks:
                    Stock.objects.filter(id__in=[stock.id for stock in duplicate_stocks]).delete()
            else:
                # Create new stock item
                Stock.objects.create(
                    shop_location=shop_location,
                    item_name=normalized_item_name,
                    hsn_code=hsn_code if hsn_code else None,
                    batch_number=batch_number if batch_number else None,
                    manufacturing_date=manufacturing_date if manufacturing_date else None,
                    exp_date=exp_date if exp_date else None,
                    quantity=quantity_to_add,
                    price=unit_price,
                    gst_percent=Decimal(gst_percent)
                )
            return redirect('admin_dashboard')
        except (ShopLocation.DoesNotExist, ValueError, InvalidOperation):
            error = "Invalid data. Please check location, quantity, and price."
            shop_locations = ShopLocation.objects.all()
            return render(request, 'admin/add_stock.html', {'error': error, 'shop_locations': shop_locations})
    
    shop_locations = ShopLocation.objects.all()
    return render(request, 'admin/add_stock.html', {'shop_locations': shop_locations})

@login_required(login_url='login')
def check_stock_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    shop_locations = ShopLocation.objects.all()
    selected_shop_location_id = request.GET.get('shop_location', '').strip()
    filter_message = ""
    stock_items = Stock.objects.none()
    selected_shop_name = ""

    if selected_shop_location_id:
        if shop_locations.filter(id=selected_shop_location_id).exists():
            raw_stock_items = Stock.objects.select_related('shop_location').filter(
                shop_location_id=selected_shop_location_id
            ).order_by('-updated_at', '-id')

            consolidated_items = {}
            for item in raw_stock_items:
                item_key = item.item_name.strip().lower()
                if item_key in consolidated_items:
                    consolidated_items[item_key].quantity += item.quantity
                else:
                    consolidated_items[item_key] = item

            stock_items = list(consolidated_items.values())
            selected_shop_name = shop_locations.get(id=selected_shop_location_id).name
        else:
            selected_shop_location_id = ""
            filter_message = "Selected shop location is invalid."
    
    # Calculate totals
    total_items = sum([item.quantity for item in stock_items])
    total_value = sum([item.quantity * item.price for item in stock_items])
    
    # Group by location
    stock_by_location = {}
    for item in stock_items:
        location_name = item.shop_location.name
        if location_name not in stock_by_location:
            stock_by_location[location_name] = []
        stock_by_location[location_name].append(item)
    
    return render(request, 'admin/check_stock.html', {
        'stock_items': stock_items,
        'stock_by_location': stock_by_location,
        'total_items': total_items,
        'total_value': total_value,
        'shop_locations': shop_locations,
        'selected_shop_location_id': selected_shop_location_id,
        'selected_shop_name': selected_shop_name,
        'filter_message': filter_message,
    })

@login_required(login_url='login')
def create_shop_location_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    if request.method == 'POST':
        location_name = request.POST.get('location_name')
        address = request.POST.get('address', '')
        
        if ShopLocation.objects.filter(name=location_name).exists():
            error = "Shop location already exists"
            return render(request, 'admin/create_shop_location.html', {'error': error})
        
        ShopLocation.objects.create(name=location_name, address=address)
        return redirect('shop_locations')
    
    return render(request, 'admin/create_shop_location.html')

@login_required(login_url='login')
def shop_locations_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    shop_locations = ShopLocation.objects.all()
    return render(request, 'admin/shop_locations.html', {
        'shop_locations': shop_locations
    })

@login_required(login_url='login')
def assign_employee_to_shop_view(request, shop_id):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    try:
        shop_location = ShopLocation.objects.get(id=shop_id)
    except ShopLocation.DoesNotExist:
        return HttpResponse("Shop location not found", status=404)
    
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        
        try:
            employee = User.objects.get(id=employee_id)
            # Check if already assigned
            if ShopEmployee.objects.filter(shop_location=shop_location, employee=employee).exists():
                error = "Employee already assigned to this shop"
                assigned_employees = ShopEmployee.objects.filter(shop_location=shop_location)
                available_employees = User.objects.filter(is_superuser=False, is_staff=False).exclude(
                    id__in=assigned_employees.values_list('employee_id', flat=True)
                )
                return render(request, 'admin/assign_employee.html', {
                    'shop_location': shop_location,
                    'available_employees': available_employees,
                    'assigned_employees': assigned_employees,
                    'error': error
                })
            
            ShopEmployee.objects.create(shop_location=shop_location, employee=employee)
            return redirect('assign_employee_to_shop', shop_id=shop_id)
        except User.DoesNotExist:
            error = "Employee not found"
            return render(request, 'admin/assign_employee.html', {'shop_location': shop_location, 'error': error})
    
    assigned_employees = ShopEmployee.objects.filter(shop_location=shop_location)
    available_employees = User.objects.filter(is_superuser=False, is_staff=False).exclude(
        id__in=assigned_employees.values_list('employee_id', flat=True)
    )
    
    return render(request, 'admin/assign_employee.html', {
        'shop_location': shop_location,
        'available_employees': available_employees,
        'assigned_employees': assigned_employees
    })

@login_required(login_url='login')
def remove_employee_from_shop_view(request, assignment_id):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    try:
        assignment = ShopEmployee.objects.get(id=assignment_id)
        shop_id = assignment.shop_location.id
        assignment.delete()
        return redirect('assign_employee_to_shop', shop_id=shop_id)
    except ShopEmployee.DoesNotExist:
        return HttpResponse("Assignment not found", status=404)

@login_required(login_url='login')
def employee_shop_stock_view(request):
    if request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    assigned_shop = ShopLocation.objects.filter(
        employees__employee=request.user
    ).distinct().first()

    if not assigned_shop:
        return JsonResponse({'stock_items': []})

    normalize_stock_for_shop(assigned_shop)
    stock_items = Stock.objects.filter(
        shop_location=assigned_shop,
        quantity__gt=0
    ).order_by('item_name')

    data = [
        {
            'id': item.id,
            'item_name': item.item_name,
            'price': str(item.price),
            'quantity': item.quantity,
            'gst_percent': str(item.gst_percent),
        }
        for item in stock_items
    ]
    return JsonResponse({'stock_items': data})

@login_required(login_url='login')
def admin_sales_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)

    shop_locations = ShopLocation.objects.all()
    selected_shop_id = request.GET.get('shop_location', '')

    sales_data = Sale.objects.none()
    dates = []
    months = []
    employees = []
    item_names = []
    
    if selected_shop_id:
        sales_data = Sale.objects.filter(shop_location_id=selected_shop_id).order_by('-sale_date')

        date_filter = request.GET.get('date', '')
        month_filter = request.GET.get('month', '')
        employee_filter = request.GET.get('employee', '')
        item_filter = request.GET.get('item_name', '')

        # Extract unique values for filters
        from django.db.models.functions import TruncDate, TruncMonth
        
        # We process manually to ensure formatting and avoid complex query logic for unique sets
        all_sales_in_shop = list(sales_data)
        
        date_set = set()
        month_set = set()
        emp_set = set()
        item_set = set()
        
        for s in all_sales_in_shop:
            local_dt = timezone.localtime(s.sale_date)
            date_str = local_dt.strftime('%Y-%m-%d')
            month_str = local_dt.strftime('%Y-%m')
            date_set.add(date_str)
            month_set.add(month_str)
            emp_set.add((s.employee.id, s.employee.username))
            item_set.add(s.item_name)
            
        dates = sorted(list(date_set), reverse=True)
        months = sorted(list(month_set), reverse=True)
        employees = sorted(list(emp_set), key=lambda x: x[1])
        item_names = sorted(list(item_set))

        if date_filter:
            sales_data = sales_data.filter(sale_date__date=date_filter)
        if month_filter:
            sales_data = sales_data.filter(sale_date__year=int(month_filter.split('-')[0]), sale_date__month=int(month_filter.split('-')[1]))
        if employee_filter:
            sales_data = sales_data.filter(employee_id=employee_filter)
        if item_filter:
            sales_data = sales_data.filter(item_name=item_filter)

    total_sales_amount = sum([s.total_amount for s in sales_data])

    context = {
        'shop_locations': shop_locations,
        'selected_shop_id': selected_shop_id,
        'sales_data': sales_data,
        'dates': dates,
        'months': months,
        'employees': employees,
        'item_names': item_names,
        'selected_date': request.GET.get('date', ''),
        'selected_month': request.GET.get('month', ''),
        'selected_employee': request.GET.get('employee', ''),
        'selected_item': request.GET.get('item_name', ''),
        'total_sales_amount': total_sales_amount,
    }
    return render(request, 'admin/check_sales.html', context)

@login_required(login_url='login')
def admin_get_sales_data(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    shop_id = request.GET.get('shop_location')
    if not shop_id:
        return JsonResponse({'error': 'No shop selected'}, status=400)
    
    try:
        shop = ShopLocation.objects.get(id=shop_id)
    except ShopLocation.DoesNotExist:
        return JsonResponse({'error': 'Invalid shop'}, status=404)
    
    # Base sales for this shop
    sales_qs = Sale.objects.filter(shop_location=shop).order_by('-sale_date')
    
    # Get all sales to extract dates and months (these are based on actual sales)
    all_sales = list(sales_qs)
    date_set = set()
    month_set = set()
    for s in all_sales:
        local_dt = timezone.localtime(s.sale_date)
        date_set.add(local_dt.strftime('%Y-%m-%d'))
        month_set.add(local_dt.strftime('%Y-%m'))
    
    # Get ALL ALLOCATED employees and items (as requested)
    allocated_employees = ShopEmployee.objects.filter(shop_location=shop).select_related('employee')
    emp_list = [{'id': ae.employee.id, 'name': ae.employee.username} for ae in allocated_employees]
    
    allocated_items = Stock.objects.filter(shop_location=shop).values_list('item_name', flat=True).distinct()
    item_list = list(allocated_items)
    
    # Apply filters if present
    date_f = request.GET.get('date')
    month_f = request.GET.get('month')
    emp_f = request.GET.get('employee')
    item_f = request.GET.get('item_name')
    
    if date_f:
        sales_qs = sales_qs.filter(sale_date__date=date_f)
    if month_f:
        try:
            y, m = map(int, month_f.split('-'))
            sales_qs = sales_qs.filter(sale_date__year=y, sale_date__month=m)
        except: pass
    if emp_f:
        sales_qs = sales_qs.filter(employee_id=emp_f)
    if item_f:
        sales_qs = sales_qs.filter(item_name=item_f)
        
    filtered_sales = [
        {
            'date': timezone.localtime(s.sale_date).strftime('%d-%m-%Y %I:%M %p'),
            'bill_id': str(s.bill_id),
            'item_name': s.item_name,
            'employee': s.employee.username,
            'farmer_name': s.farmer_name or 'N/A',
            'quantity': s.quantity,
            'discount': str(s.discount_percent),
            'gst_percent': str(s.gst_percent),
            'gst_amount': str(s.gst_amount),
            'total': str(s.total_amount)
        }
        for s in sales_qs
    ]
    
    total_amount = sum([s.total_amount for s in sales_qs])
    total_gst = sum([s.gst_amount for s in sales_qs])
    
    return JsonResponse({
        'dropdown_options': {
            'dates': sorted(list(date_set), reverse=True),
            'months': sorted(list(month_set), reverse=True),
            'employees': emp_list,
            'items': sorted(item_list)
        },
        'sales': filtered_sales,
        'total_amount': str(total_amount),
        'total_gst': str(total_gst)
    })


def _build_bill_pdf_bytes(bill_sales):
    first_sale = bill_sales[0]
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    title_style.fontName = 'Helvetica-Bold'
    title_style.fontSize = 18
    title_style.textColor = colors.HexColor('#166534')
    title_style.alignment = 1

    body_style = styles['BodyText']
    body_style.fontName = 'Helvetica'
    body_style.fontSize = 9
    body_style.leading = 12

    bill_date = timezone.localtime(first_sale.sale_date).strftime('%d-%m-%Y %I:%M %p')
    customer_name = first_sale.farmer_name or 'Walk-in Customer'
    customer_phone = first_sale.farmer_phone or '-'
    bill_number = str(first_sale.bill_id).upper()

    table_data = [[
        Paragraph('<b>Item</b>', body_style),
        Paragraph('<b>HSN</b>', body_style),
        Paragraph('<b>Qty</b>', body_style),
        Paragraph('<b>Rate</b>', body_style),
        Paragraph('<b>Disc.</b>', body_style),
        Paragraph('<b>GST</b>', body_style),
        Paragraph('<b>Total</b>', body_style),
    ]]
    subtotal = Decimal('0.00')
    total_gst = Decimal('0.00')
    total_amount = Decimal('0.00')
    for sale in bill_sales:
        subtotal += sale.unit_price * sale.quantity
        total_gst += sale.gst_amount
        total_amount += sale.total_amount
        table_data.append([
            Paragraph(str(sale.item_name), body_style),
            Paragraph(str(sale.hsn_code or '-'), body_style),
            str(sale.quantity),
            f'Rs. {sale.unit_price:.2f}',
            f'{sale.discount_percent:.2f}%',
            f'Rs. {sale.gst_amount:.2f}',
            f'Rs. {sale.total_amount:.2f}',
        ])

    table = Table(table_data, colWidths=[110, 45, 35, 58, 48, 58, 65], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#15803d')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bbf7d0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fdf4')]),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    amount_paid = first_sale.amount_paid
    balance_due = max(total_amount - amount_paid, Decimal('0.00'))
    story = [
        Paragraph('SALES BILL', title_style),
        Spacer(1, 10),
        Paragraph(f'<b>Bill No:</b> {bill_number}<br/><b>Date:</b> {bill_date}<br/><b>Shop:</b> {first_sale.shop_location.name}<br/><b>Customer:</b> {customer_name} ({customer_phone})<br/><b>Employee:</b> {first_sale.employee.username}', body_style),
        Spacer(1, 12),
        table,
        Spacer(1, 12),
        Paragraph(f'<b>Subtotal:</b> Rs. {subtotal:.2f}<br/><b>Total GST:</b> Rs. {total_gst:.2f}<br/><b>Grand Total:</b> Rs. {total_amount:.2f}<br/><b>Amount Paid:</b> Rs. {amount_paid:.2f}<br/><b>Balance Due:</b> Rs. {balance_due:.2f}', body_style),
        Spacer(1, 16),
        Paragraph('Thank you for your purchase.', body_style),
    ]

    buffer = __import__('io').BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    document.build(story)
    return buffer.getvalue()


@login_required(login_url='login')
def admin_bill_pdf_view(request, bill_id):
    if not request.user.is_superuser:
        return HttpResponse('Unauthorized', status=403)

    bill_sales = list(Sale.objects.filter(bill_id=bill_id).select_related('shop_location', 'employee').order_by('sale_date', 'id'))
    if not bill_sales:
        return HttpResponse('Bill not found', status=404)

    pdf_data = _build_bill_pdf_bytes(bill_sales)
    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bill_{bill_id}.pdf"'
    return response

@login_required(login_url='login')
def delete_employee(request, user_id):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    
    try:
        user = User.objects.get(id=user_id, is_superuser=False)
        user.delete()
    except User.DoesNotExist:
        pass
        
    return redirect('admin_dashboard')

@login_required(login_url='login')
def delete_stock_view(request, stock_id):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)

    if request.method == 'POST':
        try:
            stock_item = Stock.objects.get(id=stock_id)
            shop_id = stock_item.shop_location_id
            stock_item.delete()
            return redirect(f'/check-stock/?shop_location={shop_id}')
        except Stock.DoesNotExist:
            pass

    return redirect('check_stock')

@login_required(login_url='login')
def delete_shop_location_view(request, shop_id):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)

    if request.method == 'POST':
        try:
            shop_location = ShopLocation.objects.get(id=shop_id)
            shop_location.delete()
            return redirect('shop_locations')
        except ShopLocation.DoesNotExist:
            pass

    return redirect('shop_locations')

@login_required(login_url='login')
def farmer_search_view(request):
    """API endpoint to search farmers by name for autocomplete suggestions."""
    query = request.GET.get('q', '').strip()
    if not query or len(query) < 1:
        return JsonResponse({'farmers': []})

    farmers = Farmer.objects.filter(name__icontains=query).values('name', 'phone')[:10]
    return JsonResponse({'farmers': list(farmers)})

def _build_farmer_due_pdf_bytes(rows, title='Farmer Due Statement'):
    if not rows:
        rows = [{"name": "No Farmer", "phone": "-", "due_amount": Decimal('0.00')}]

    logo_path = settings.BASE_DIR / 'static' / 'logo.png'
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    title_style.fontName = 'Helvetica-Bold'
    title_style.fontSize = 18
    title_style.textColor = colors.HexColor('#166534')
    title_style.alignment = 1

    body_style = styles['BodyText']
    body_style.fontName = 'Helvetica'
    body_style.fontSize = 10
    body_style.leading = 14

    table_data = [[Paragraph('<b>Farmer Name</b>', body_style), Paragraph('<b>Phone Number</b>', body_style), Paragraph('<b>Due Amount</b>', body_style)]]
    for row in rows:
        table_data.append([
            Paragraph(str(row.get('name', 'Unknown Farmer')), body_style),
            Paragraph(str(row.get('phone', '-')), body_style),
            Paragraph(f'Rs. {Decimal(str(row.get("due_amount", 0))):.2f}', body_style),
        ])

    table = Table(table_data, colWidths=[170, 140, 120], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#15803d')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bbf7d0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fdf4')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 7),
        ('TOPPADDING', (0, 1), (-1, -1), 7),
    ]))

    story = []
    if logo_path.exists():
        story.append(Image(str(logo_path), width=28*mm, height=20*mm))
        story.append(Spacer(1, 8))
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 14))
    story.append(table)
    story.append(Spacer(1, 16))
    story.append(Paragraph('Supraja Farmer Due Statement', body_style))

    buffer = __import__('io').BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=24, rightMargin=24, topMargin=20, bottomMargin=20)
    document.build(story)
    return buffer.getvalue()


@login_required(login_url='login')
def farmer_due_pdf_view(request, farmer_id=None):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)

    if farmer_id is not None:
        farmer = Farmer.objects.filter(id=farmer_id).first()
        if not farmer:
            return HttpResponse("Farmer not found", status=404)
        farmer_rows = [{
            'name': farmer.name,
            'phone': farmer.phone,
            'due_amount': Decimal('0.00'),
        }]
        sales = Sale.objects.filter(farmer=farmer).order_by('sale_date')
        current_bill_sales = []
        bills = []

        for sale in sales:
            if not current_bill_sales:
                current_bill_sales.append(sale)
            else:
                time_diff = (sale.sale_date - current_bill_sales[0].sale_date).total_seconds()
                if abs(time_diff) < 5:
                    current_bill_sales.append(sale)
                else:
                    bills.append(current_bill_sales)
                    current_bill_sales = [sale]
        if current_bill_sales:
            bills.append(current_bill_sales)

        for bill_sales in bills:
            bill_total = sum(s.total_amount for s in bill_sales)
            bill_paid = bill_sales[0].amount_paid
            due = bill_total - bill_paid
            if due > 0:
                farmer_rows[0]['due_amount'] += due

        pdf_data = _build_farmer_due_pdf_bytes([
            {
                'name': farmer_rows[0]['name'],
                'phone': farmer_rows[0]['phone'],
                'due_amount': farmer_rows[0]['due_amount'],
            }
        ], f"Farmer Due Statement - {farmer.name}")
        response = HttpResponse(pdf_data, content_type='application/pdf')
        filename = f"farmer_due_{farmer.name.replace(' ', '_')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    farmer_rows = []
    for farmer in Farmer.objects.all():
        sales = Sale.objects.filter(farmer=farmer).order_by('sale_date')
        current_bill_sales = []
        bills = []

        for sale in sales:
            if not current_bill_sales:
                current_bill_sales.append(sale)
            else:
                time_diff = (sale.sale_date - current_bill_sales[0].sale_date).total_seconds()
                if abs(time_diff) < 5:
                    current_bill_sales.append(sale)
                else:
                    bills.append(current_bill_sales)
                    current_bill_sales = [sale]
        if current_bill_sales:
            bills.append(current_bill_sales)

        total_due = Decimal('0.00')
        for bill_sales in bills:
            bill_total = sum(s.total_amount for s in bill_sales)
            bill_paid = bill_sales[0].amount_paid
            due = bill_total - bill_paid
            if due > 0:
                total_due += due

        if total_due > 0:
            farmer_rows.append({
                'name': farmer.name,
                'phone': farmer.phone,
                'due_amount': total_due,
            })

    if not farmer_rows:
        return HttpResponse("No farmers with dues found", status=404)

    pdf_data = _build_farmer_due_pdf_bytes(farmer_rows, 'All Farmers with Due Amounts')
    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="all_farmers_due.pdf"'
    return response


@login_required(login_url='login')
def admin_farmers_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
        
    from django.db.models import Q

    filter_dues = request.GET.get('filter') == 'dues'
    search_query = request.GET.get('search', '').strip()
    
    if search_query:
        all_farmers = Farmer.objects.filter(
            Q(name__icontains=search_query) | Q(phone__icontains=search_query)
        )
    else:
        all_farmers = Farmer.objects.all()
    
    farmer_data_list = []
    
    for farmer in all_farmers:
        # Get all sales for this farmer, ordered by date
        sales = Sale.objects.filter(farmer=farmer).order_by('sale_date')
        
        total_bought = Decimal('0.00')
        total_paid = Decimal('0.00')
        due_bills = []
        
        current_bill_sales = []
        
        def process_bill_sales(bill_sales):
            nonlocal total_bought, total_paid
            if not bill_sales:
                return
            bill_total = sum(s.total_amount for s in bill_sales)
            bill_paid = bill_sales[0].amount_paid
            total_bought += bill_total
            total_paid += bill_paid
            
            due = bill_total - bill_paid
            if due > 0:
                products_str = ", ".join([f"{s.item_name} (x{s.quantity})" for s in bill_sales])
                due_bills.append({
                    'date': timezone.localtime(bill_sales[0].sale_date).strftime('%d-%m-%Y %I:%M %p'),
                    'products': products_str,
                    'bill_total': bill_total,
                    'bill_paid': bill_paid,
                    'due_amount': due,
                })

        for sale in sales:
            if not current_bill_sales:
                current_bill_sales.append(sale)
            else:
                # Group if sales are within 5 seconds of each other
                time_diff = (sale.sale_date - current_bill_sales[0].sale_date).total_seconds()
                if abs(time_diff) < 5:
                    current_bill_sales.append(sale)
                else:
                    process_bill_sales(current_bill_sales)
                    current_bill_sales = [sale]
                    
        # Process the last bill
        process_bill_sales(current_bill_sales)
            
        total_dues = total_bought - total_paid
        if total_dues < 0: 
            total_dues = Decimal('0.00')
            
        # Only add to list if not filtering by dues OR if filtering by dues and dues > 0
        if not filter_dues or total_dues > 0:
            farmer_data_list.append({
                'id': farmer.id,
                'name': farmer.name,
                'phone': farmer.phone,
                'total_bought': total_bought,
                'total_paid': total_paid,
                'total_dues': total_dues,
                'due_bills': due_bills,
            })
            
    # Sort by name ascending
    farmer_data_list.sort(key=lambda x: x['name'].lower())
    
    return render(request, 'admin/farmers.html', {
        'farmers': farmer_data_list,
        'filter_dues': filter_dues,
        'search_query': search_query,
        'error': request.GET.get('error'),
        'success': request.GET.get('success'),
    })

@login_required(login_url='login')
def clear_farmer_due_view(request):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
        
    if request.method == 'POST':
        farmer_id = request.POST.get('farmer_id')
        try:
            clear_amount = Decimal(request.POST.get('clear_amount', '0'))
        except (ValueError, InvalidOperation):
            clear_amount = Decimal('0.00')

        if clear_amount <= 0:
            return redirect('/admin-farmers/?filter=dues')
            
        farmer = Farmer.objects.filter(id=farmer_id).first()
        if not farmer:
            return redirect('/admin-farmers/?filter=dues')

        # Fetch sales and group into bills
        sales = Sale.objects.filter(farmer=farmer).order_by('sale_date')
        bills = []
        current_bill_sales = []

        for sale in sales:
            if not current_bill_sales:
                current_bill_sales.append(sale)
            else:
                time_diff = (sale.sale_date - current_bill_sales[0].sale_date).total_seconds()
                if abs(time_diff) < 5:
                    current_bill_sales.append(sale)
                else:
                    bills.append(current_bill_sales)
                    current_bill_sales = [sale]
        if current_bill_sales:
            bills.append(current_bill_sales)

        # Calculate due per bill
        due_bills = []
        total_farmer_dues = Decimal('0.00')
        for bill_sales in bills:
            bill_total = sum(s.total_amount for s in bill_sales)
            bill_paid = bill_sales[0].amount_paid
            due = bill_total - bill_paid
            if due > 0:
                total_farmer_dues += due
                due_bills.append({
                    'sales': bill_sales,
                    'bill_total': bill_total,
                    'bill_paid': bill_paid,
                    'due': due,
                })

        # Validate clear_amount <= total_farmer_dues
        if clear_amount > total_farmer_dues:
            error_msg = f"Clear amount (Rs. {clear_amount:.2f}) cannot exceed total dues (Rs. {total_farmer_dues:.2f})."
            from urllib.parse import quote
            return redirect(f'/admin-farmers/?filter=dues&error={quote(error_msg)}')

        # Sort due_bills by due amount descending (deduct from bill with highest due first)
        due_bills.sort(key=lambda b: b['due'], reverse=True)

        # Distribute clear_amount
        remaining = clear_amount
        for b in due_bills:
            if remaining <= 0:
                break
            add_to_bill = min(remaining, b['due'])
            new_bill_paid = b['bill_paid'] + add_to_bill
            
            for sale in b['sales']:
                sale.amount_paid = new_bill_paid
                sale.save()

            remaining -= add_to_bill

        success_msg = f"Successfully cleared Rs. {clear_amount:.2f} for {farmer.name}!"
        from urllib.parse import quote
        return redirect(f'/admin-farmers/?filter=dues&success={quote(success_msg)}')

    return redirect('/admin-farmers/?filter=dues')
