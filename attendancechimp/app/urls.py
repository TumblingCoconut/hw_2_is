from django.urls import path
from . import views

urlpatterns = [
    path('time', views.time_view, name='time'),
    path('sum', views.sum_view, name='sum'),
]
