from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from employee.models import Stock

@login_required(login_url='login')
def delete_stock_view(request, stock_id):
    if not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=403)
    stock = get_object_or_404(Stock, id=stock_id)
    shop_location_id = stock.shop_location.id
    stock.delete()
    # Redirect back to check-stock with the same shop location selected
    return redirect(f'/check-stock/?shop_location={shop_location_id}')
