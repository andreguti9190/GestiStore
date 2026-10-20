from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone
from .models import Producto


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ['nombre', 'descripcion', 'precio', 'stock', 'categoria',
                  'imagen', 'peso_kg', 'activo']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 4}),
        }


class RegistroForm(UserCreationForm):
    email = forms.EmailField(required=True)
    fecha_nacimiento = forms.DateField(
        required=True,
        label='Fecha de nacimiento',
        widget=forms.DateInput(attrs={
            'type': 'date',
            'autocomplete': 'bday',
        }),
        error_messages={
            'required': 'Ingresá tu fecha de nacimiento.',
            'invalid': 'Ingresá una fecha de nacimiento válida.',
        },
    )
    acepta_terminos = forms.BooleanField(
        required=True,
        label='Acepto los Términos y Condiciones',
        error_messages={
            'required': 'Tenés que aceptar los Términos y Condiciones para crear tu cuenta.',
        },
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'fecha_nacimiento', 'password1', 'password2',
            'acepta_terminos',
        ]

    def __init__(self, *args, pending_user=None, **kwargs):
        if pending_user is not None:
            kwargs['instance'] = pending_user
        super().__init__(*args, **kwargs)
        self.pending_user = pending_user

    def clean_username(self):
        username = self.cleaned_data.get('username')
        existing = User.objects.filter(username__iexact=username)
        if self.pending_user:
            existing = existing.exclude(pk=self.pending_user.pk)
        if username and existing.exists():
            raise forms.ValidationError('Ya existe una cuenta con ese nombre de usuario.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        existing = User.objects.filter(email__iexact=email)
        if self.pending_user:
            existing = existing.exclude(pk=self.pending_user.pk)
        if existing.exists():
            raise forms.ValidationError('Ya existe una cuenta con este email.')
        return email

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']
        hoy = timezone.localdate()
        try:
            limite_mayoria_edad = hoy.replace(year=hoy.year - 18)
        except ValueError:
            # El 29 de febrero cumple años legalmente, como máximo, el 28 en
            # los años no bisiestos para esta validación de acceso.
            limite_mayoria_edad = hoy.replace(year=hoy.year - 18, day=28)

        if fecha > hoy:
            raise forms.ValidationError('La fecha de nacimiento no puede ser futura.')
        if fecha > limite_mayoria_edad:
            raise forms.ValidationError('Tenés que ser mayor de 18 años para crear una cuenta.')
        return fecha


class LoginForm(AuthenticationForm):
    """Primer factor: usuario y contraseña."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Usuario o contraseña incorrectos.',
    }
