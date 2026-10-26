from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone
from .models import Producto


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ['nombre', 'sku', 'descripcion', 'precio', 'costo', 'stock', 'categoria',
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
    responsable_nombre = forms.CharField(
        required=False,
        max_length=120,
        label='Nombre y apellido del adulto responsable',
        widget=forms.TextInput(attrs={'autocomplete': 'name'}),
    )
    responsable_dni = forms.CharField(
        required=False,
        max_length=12,
        label='DNI del adulto responsable',
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}),
    )
    responsable_parentesco = forms.CharField(
        required=False,
        max_length=40,
        label='Vínculo con el menor',
        widget=forms.TextInput(attrs={'placeholder': 'Madre, padre, tutor…'}),
    )
    autorizacion_responsable = forms.BooleanField(
        required=False,
        label='El adulto responsable autoriza las compras de esta cuenta',
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
            'username', 'email', 'fecha_nacimiento', 'responsable_nombre',
            'responsable_dni', 'responsable_parentesco', 'autorizacion_responsable',
            'password1', 'password2',
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
        if fecha > hoy:
            raise forms.ValidationError('La fecha de nacimiento no puede ser futura.')
        return fecha

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get('fecha_nacimiento')
        if not fecha:
            return cleaned
        hoy = timezone.localdate()
        edad = hoy.year - fecha.year - ((hoy.month, hoy.day) < (fecha.month, fecha.day))
        if edad >= 18:
            cleaned['es_menor'] = False
            return cleaned

        cleaned['es_menor'] = True
        nombre = (cleaned.get('responsable_nombre') or '').strip()
        dni = ''.join(character for character in (cleaned.get('responsable_dni') or '') if character.isdigit())
        parentesco = (cleaned.get('responsable_parentesco') or '').strip()
        if not nombre:
            self.add_error('responsable_nombre', 'Ingresá el nombre del adulto responsable.')
        if not 7 <= len(dni) <= 9:
            self.add_error('responsable_dni', 'Ingresá un DNI válido de 7 a 9 dígitos.')
        else:
            cleaned['responsable_dni'] = dni
        if not parentesco:
            self.add_error('responsable_parentesco', 'Indicá el vínculo con el menor.')
        if not cleaned.get('autorizacion_responsable'):
            self.add_error(
                'autorizacion_responsable',
                'El adulto responsable debe autorizar las compras de la cuenta.',
            )
        return cleaned


class LoginForm(AuthenticationForm):
    """Primer factor: usuario y contraseña."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Usuario o contraseña incorrectos.',
    }
