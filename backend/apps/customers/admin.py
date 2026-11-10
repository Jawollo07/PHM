from django.contrib import admin

from .models import Customer, CustomerAddress, CustomerSettings


admin.site.register(Customer)
admin.site.register(CustomerAddress)
admin.site.register(CustomerSettings)
