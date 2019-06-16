from django import forms
from django.forms import CharField, TextInput, CheckboxInput, Textarea
from django.forms import ModelForm

from adminconsole.models import AppEnv, App


class ProjectForm(forms.Form):
    project_slug = CharField(label='App Name', max_length=100,
                                   widget=TextInput(attrs={'readonly': 'readonly', 'class': 'form-control'}))
    organisation_name = CharField(label='Name der Genossenschaft', max_length=100,
                                        widget=TextInput(attrs={'class': 'form-control'}))
    street = CharField(label='Strasse', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    number = CharField(label='Nummer', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    zip = CharField(label='PLZ', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    city = CharField(label='Stadt', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    extra = CharField(label='AdressZusatz', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    PC = CharField(label='PC Kontonummer', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    IBAN = CharField(label='IBAN', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    BIC = CharField(label='BIC', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    NAME = CharField(label='Name der Bank', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    ESR = CharField(label='ESR falls vorhanden', max_length=100,
                          widget=TextInput(attrs={'class': 'form-control'}), required=False)
    info_email = CharField(label='info email adresse', max_length=100,
                                 widget=TextInput(attrs={'class': 'form-control'}))
    admin_portal_name = CharField(label='Name des adminposrtals', max_length=100,
                                        widget=TextInput(attrs={'class': 'form-control'}))
    admin_portal_url = CharField(label='URL des admin portals', max_length=100,
                                       widget=TextInput(attrs={'class': 'form-control'}))
    share_price = CharField(label='Preis eines Anteilscheines', max_length=100,
                                  widget=TextInput(attrs={'class': 'form-control'}))


class EnvForm(ModelForm):
    class Meta:
        model = AppEnv
        fields = ['juntagrico_admin_email', 'juntagrico_email_host',
                  'juntagrico_email_password', 'juntagrico_email_port',
                  'juntagrico_email_user', 'juntagrico_email_tls',
                  'juntagrico_email_ssl', 'google_api_key', 'various']
        widgets = {
            'juntagrico_admin_email': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_host_email': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_host': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_password': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_port': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_user': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_tls': CheckboxInput(attrs={'class': 'form-control'}),
            'juntagrico_email_ssl': CheckboxInput(attrs={'class': 'form-control'}),
            'google_api_key': TextInput(attrs={'class': 'form-control'}),
            'various': Textarea(attrs={'class': 'form-control'})
        }


class AppForm(ModelForm):
    class Meta:
        model = App
        fields = ['name', 'managed']
        widgets = {
            'name': TextInput(attrs={'class': 'form-control'}),
            'managed': CheckboxInput(attrs={'class': 'onoffswitch'})
        }


class DomainForm(forms.Form):
    domain = CharField(label='Domain', max_length=100,
                             widget=TextInput(attrs={'class': 'form-control'}))
