from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from .models import User

MAX_PHOTO_MB = 2


class RegisterForm(UserCreationForm):
    """Registration: required fields, valid + unique email, matching passwords.

    UserCreationForm checks that password1 and password2 match, runs the
    password validators, and saves the password as a hash.
    """

    full_name = forms.CharField(max_length=100, label="Full name")
    email = forms.EmailField(max_length=100, label="Email address")
    contact_number = forms.CharField(max_length=13, required=False, label="Contact number",
                                     help_text="Example: 09171234567")
    role = forms.ChoiceField(choices=User.Role.choices, label="I am the",
                             widget=forms.RadioSelect, initial=User.Role.HELPER)

    class Meta:
        model = User
        fields = ("full_name", "email", "contact_number", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Password"
        self.fields["password2"].label = "Confirm password"
        self.fields["password2"].help_text = "Type the same password again."
        self.fields["email"].widget.attrs.update(autocomplete="email", autofocus=True)
        self.fields["full_name"].widget.attrs.update(autocomplete="name")
        self.fields["contact_number"].widget.attrs.update(autocomplete="tel", inputmode="tel")

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if not name:
            raise forms.ValidationError("Enter your full name.")
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Log in instead.")
        return email

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("The two passwords don't match.")
        return p2


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Incorrect email or password. Check both and try again.",
        "inactive": "This account has been deactivated. Ask the store owner for help.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Email address"
        self.fields["username"].widget = forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email"}
        )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(forms.ModelForm):
    """Fields a user may change on their own profile. Role is NOT editable here."""

    class Meta:
        model = User
        fields = ("full_name", "email", "contact_number", "profile_photo")
        labels = {"full_name": "Full name", "email": "Email address",
                  "contact_number": "Contact number", "profile_photo": "Profile photo"}
        help_texts = {"contact_number": "Example: 09171234567",
                      "profile_photo": f"JPG, PNG or WebP, up to {MAX_PHOTO_MB} MB."}
        widgets = {"profile_photo": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})}

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if not name:
            raise forms.ValidationError("Enter your full name.")
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO_MB * 1024 * 1024:
            raise forms.ValidationError(f"The photo is larger than {MAX_PHOTO_MB} MB. Choose a smaller file.")
        return photo


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = password_validation.password_validators_help_text_html()
        self.fields["new_password2"].label = "Confirm new password"
