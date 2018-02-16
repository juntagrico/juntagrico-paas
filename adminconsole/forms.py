from django import forms
from django.forms import CharField, TextInput
from django.forms import ModelForm

from  adminconsole.models import AppEnv

class ProjectForm(forms.Form):
    project_slug = forms.CharField(label='App Name', max_length=100, widget=TextInput(attrs={'readonly':'readonly', 'class': 'form-control'}))
    organisation_name = forms.CharField(label='Name der Genossenschaft', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    street = forms.CharField(label='Strasse', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    number = forms.CharField(label='Nummer', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    zip = forms.CharField(label='PLZ', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    city = forms.CharField(label='Stadt', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    extra = forms.CharField(label='AdressZusatz', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    PC = forms.CharField(label='PC Kontonummer', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    IBAN = forms.CharField(label='IBAN', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    BIC = forms.CharField(label='BIC', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    NAME = forms.CharField(label='Name der Bank', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    ESR = forms.CharField(label='ESR falls vorhanden', max_length=100, widget=TextInput(attrs={'class': 'form-control'}), required=False)
    info_email = forms.CharField(label='info email adresse', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    admin_portal_name = forms.CharField(label='Name des adminposrtals', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    admin_portal_url = forms.CharField(label='URL des admin portals', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    share_price = forms.CharField(label='Preis eines Anteilscheines', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))

class EnvForm(ModelForm):
   class Meta: 
        model = AppEnv
        fields = ['juntagrico_admin_email', 'juntagrico_host_email', 'juntagrico_email_host', 'juntagrico_email_password', 'juntagrico_email_port', 'juntagrico_email_user', 'google_api_key']
        widgets = {
            'juntagrico_admin_email': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_host_email': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_host': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_password': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_port': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_user': TextInput(attrs={'class': 'form-control'}),
            'google_api_key': TextInput(attrs={'class': 'form-control'})
       }
