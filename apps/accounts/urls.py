from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Auth
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('forgot-password/', views.ForgotPasswordView.as_view(), name='forgot_password'),
    path(
        'reset-password/<str:uidb64>/<str:token>/',
        views.ResetPasswordView.as_view(), name='reset_password',
    ),

    # User management
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path('users/<int:pk>/edit/', views.UserEditView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),
    path(
        'users/<int:pk>/toggle-active/',
        views.UserToggleActiveView.as_view(), name='user_toggle_active',
    ),

    # Profile
    path('profile/', views.UserProfileView.as_view(), name='profile'),
    path('profile/edit/', views.UserProfileEditView.as_view(), name='profile_edit'),
    path(
        'profile/change-password/',
        views.ChangePasswordView.as_view(), name='change_password',
    ),

    # Invites
    path('invites/', views.UserInviteListView.as_view(), name='invite_list'),
    path('invites/send/', views.UserInviteSendView.as_view(), name='invite_send'),
    path(
        'invites/<int:pk>/cancel/',
        views.UserInviteCancelView.as_view(), name='invite_cancel',
    ),
    path(
        'invites/<int:pk>/resend/',
        views.UserInviteResendView.as_view(), name='invite_resend',
    ),
    path(
        'invites/accept/<uuid:token>/',
        views.AcceptInviteView.as_view(), name='accept_invite',
    ),
]
