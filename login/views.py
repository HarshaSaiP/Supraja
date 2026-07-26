from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from datetime import date
from employee.models import ShopLocation, ShopEmployee, Stock, Sale

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

            total_final_price = Decimal('0.00')
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
                            shop_location_id=pending_sale['shop_id'],
                            employee=request.user,
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
            'item_name': s.item_name,
            'employee': s.employee.username,
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
