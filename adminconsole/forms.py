import ipaddress
import smtplib
import socket
import ssl

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import get_connection
from django.core.validators import RegexValidator
from django.forms import CharField, TextInput, CheckboxInput, Textarea, EmailField, BooleanField, RadioSelect, Select

from adminconsole.models import AppEnv, App, Domain, AppCronjob, get_available_cronjobs

# ports of mail servers, the connection test is only made to these ports (setting SMTP_CHECK_PORTS)
SMTP_CHECK_PORTS = (25, 465, 587, 2525)


def is_public_address(address):
    ip = ipaddress.ip_address(address.split('%')[0])  # strip the scope of IPv6 link-local addresses
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def smtp_target_error(host, port):
    """
    Returns why the console must not connect to the mail server, or None.
    The connection test runs in the console, so it must not reach hosts and ports in the console's own network.
    """
    if not host:
        return 'Es ist kein E-Mail-Server angegeben.'
    allowed_ports = getattr(settings, 'SMTP_CHECK_PORTS', SMTP_CHECK_PORTS)
    if port not in allowed_ports:
        return f'Die Verbindung kann nur für die Ports {", ".join(map(str, allowed_ports))} geprüft werden.'
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        return 'Der E-Mail-Server wurde nicht gefunden. Prüfe den Servernamen.'
    if not addresses or not all(is_public_address(address) for address in addresses):
        return 'Die Verbindung zu Servern im internen Netz kann nicht geprüft werden.'
    return None


def smtp_connection_error(connection):
    """ connects to the mail server, returns a message for the user if it fails or None """
    try:
        connection.open()
        connection.close()
    except smtplib.SMTPAuthenticationError as e:
        # the answer of a public mail server, often with a hint (e.g. about app passwords)
        answer = e.smtp_error.decode('utf-8', 'replace') if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return f'Anmeldung fehlgeschlagen. Antwort des Servers: {answer[:300]}'
    except (ssl.SSLError, smtplib.SMTPNotSupportedError):
        return 'TLS/SSL-Verbindung fehlgeschlagen. Prüfe die Einstellung TLS bzw. SSL und den Port.'
    except ConnectionRefusedError:
        return 'Der Server lehnt die Verbindung ab. Prüfe den Port.'
    except TimeoutError:
        return 'Der Server antwortet nicht. Prüfe Server und Port.'
    except (OSError, smtplib.SMTPException):
        # no details: they could reveal information about the network
        return 'Verbindung zum E-Mail-Server fehlgeschlagen. Prüfe deine Einstellungen.'
    return None


class ProjectForm(forms.Form):
    project_slug = CharField(
        label='App Name', max_length=100,
        validators=[RegexValidator(regex='^[a-z0-9]+$')],
        widget=TextInput(attrs={'readonly': 'readonly', 'class': 'form-control'})
    )
    organisation_name = CharField(
        label='Name der Genossenschaft', max_length=100,
        widget=TextInput(attrs={'class': 'form-control'})
    )
    street = CharField(label='Strasse', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    number = CharField(label='Nummer', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    zip = CharField(label='PLZ', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    city = CharField(label='Stadt', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    extra = CharField(
        label='AdressZusatz', max_length=100, required=False,
        widget=TextInput(attrs={'class': 'form-control'})
    )
    PC = CharField(label='PC Kontonummer', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    IBAN = CharField(label='IBAN', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    BIC = CharField(label='BIC', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    NAME = CharField(label='Name der Bank', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))
    ESR = CharField(
        label='ESR falls vorhanden', max_length=100, required=False,
        widget=TextInput(attrs={'class': 'form-control'})
    )
    info_email = CharField(
        label='info email adresse', max_length=100,
        widget=TextInput(attrs={'class': 'form-control'})
    )
    share_price = CharField(
        label='Preis eines Anteilscheines', max_length=100,
        widget=TextInput(attrs={'class': 'form-control'})
    )


class EnvForm(forms.ModelForm):
    class Meta:
        model = AppEnv
        fields = ['juntagrico_admin_email',
                  'juntagrico_email_user',
                  'juntagrico_email_password',
                  'juntagrico_email_host',
                  'juntagrico_email_port',
                  'juntagrico_email_tls',
                  'juntagrico_email_ssl',
                  'juntagrico_secret_key',
                  'various']
        widgets = {
            'juntagrico_admin_email': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_user': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_password': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_host': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_port': TextInput(attrs={'class': 'form-control'}),
            'juntagrico_email_tls': CheckboxInput(attrs={'class': 'form-control'}),
            'juntagrico_email_ssl': CheckboxInput(attrs={'class': 'form-control'}),
            'juntagrico_secret_key': TextInput(attrs={'class': 'form-control'}),
            'various': Textarea(attrs={'class': 'form-control'})
        }

    def clean(self):
        cleaned_data = super().clean()
        use_tls = cleaned_data.get('juntagrico_email_tls')
        use_ssl = cleaned_data.get('juntagrico_email_ssl')
        if use_tls and use_ssl:
            raise ValidationError(
                'Es kann nur entweder TLS oder SSL ausgewählt werden.',
                code='ssl_error'
            )
        if 'skip_check' not in self.data:
            error = self.check_smtp_connection(cleaned_data, use_tls, use_ssl)
            if error:
                raise ValidationError(error, code='smtp_error')
        return cleaned_data

    @staticmethod
    def check_smtp_connection(cleaned_data, use_tls, use_ssl):
        host = cleaned_data.get('juntagrico_email_host')
        try:
            port = int(cleaned_data.get('juntagrico_email_port') or 25)
        except ValueError:
            return 'Der Port muss eine Zahl sein.'

        error = smtp_target_error(host, port)
        if error:
            return error
        return smtp_connection_error(get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=host,
            port=port,
            username=cleaned_data.get('juntagrico_email_user'),
            password=cleaned_data.get('juntagrico_email_password'),
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout=5,
        ))


class AppForm(forms.ModelForm):
    def clean_name(self):
        name = self.cleaned_data["name"]
        if '-' in name:
            raise ValidationError("Name darf nur Kleinbuchstaben und Zahlen enthalten.")
        return name

    class Meta:
        model = App
        fields = ['name', 'managed']
        widgets = {
            'name': TextInput(attrs={'class': 'form-control', 'aria-describedby': 'app_name_help'}),
            'managed': CheckboxInput(attrs={'class': 'switch', 'aria-describedby': 'managed_help'})
        }


class OverwriteAppForm(forms.Form):
    overwrite = BooleanField(label='Überschreiben', required=False, initial=False, widget=RadioSelect(
        choices=[
            (False, 'Nicht Überschreiben! Das Repo enthält bereits eine Juntagrico app.'),
            (True, 'Überschreibe alles im Repo mit einer neuen Juntagrico app.'),
        ]
    ))


class DomainForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = ['name']
        labels = {
            'name': 'Domainname',
        }
        help_texts = {
            'name': 'Ohne https://',
        }
        widgets = {
            'name': TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.app = app


class BranchForm(forms.Form):
    branch = CharField(label='Branch', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))


class PythonVersionForm(forms.ModelForm):
    class Meta:
        model = App
        fields = ['python_version']
        widgets = {
            'python_version': Select(attrs={'class': 'custom-select'}),
        }


class ProfileForm(forms.Form):
    email = EmailField(label='email adresse', max_length=100, widget=TextInput(attrs={'class': 'form-control'}))


class CronjobForm(forms.Form):
    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        available = get_available_cronjobs(app.name)
        current_ids = {ac.cronjob_id for ac in app.cronjobs.all()}
        current_map = {ac.cronjob_id: ac for ac in app.cronjobs.all()}

        # Group cronjobs by group, separating required from optional
        groups = {}
        standalone = []
        required = []
        for cj in available:
            if cj.get('required'):
                required.append(cj)
            elif cj.get('group'):
                groups.setdefault(cj['group'], []).append(cj)
            else:
                standalone.append(cj)

        self.groups = groups
        self.standalone = standalone
        self.required = required
        self.current_ids = current_ids
        self.current_map = current_map

        # Track which groups have a currently selected cronjob
        self.group_selected = {}
        for group_name, cj_list in groups.items():
            group_ids = {cj['id'] for cj in cj_list}
            self.group_selected[group_name] = bool(current_ids & group_ids)

        # Build minute choices (0-59)
        minute_choices = [(m, str(m)) for m in range(60)]
        # Build hour choices (0-23)
        hour_choices = [(h, str(h)) for h in range(24)]

        # Store for template access
        self.minute_choices = minute_choices
        self.hour_choices = hour_choices
        self.default_minute = app.port % 60

    def save(self):
        """Save cronjob selections to the database."""
        # Collect all selected cronjob ids
        selected_ids = set()

        # Required cronjobs are always selected
        for cj_def in self.required:
            selected_ids.add(cj_def['id'])

        # Grouped cronjobs: radio buttons use name="group_{group_name}" with value=cj.id
        for group_name, cj_list in self.groups.items():
            field_name = f'group_{group_name}'
            selected_id = self.data.get(field_name)
            if selected_id:
                selected_ids.add(selected_id)

        # Standalone cronjobs: checkboxes use name="cronjob_{cj.id}" with value="on"
        for cj_def in self.standalone:
            field_name = f'cronjob_{cj_def["id"]}'
            if field_name in self.data and self.data[field_name]:
                selected_ids.add(cj_def['id'])

        # Delete unselected cronjobs (but never delete required ones)
        required_ids = {cj['id'] for cj in self.required}
        self.app.cronjobs.exclude(cronjob_id__in=selected_ids).exclude(cronjob_id__in=required_ids).delete()

        # Create or update selected cronjobs with timing values
        all_cronjobs = [self.required] + list(self.groups.values()) + [self.standalone]
        for cj_list in all_cronjobs:
            for cj_def in cj_list:
                if cj_def['id'] not in selected_ids:
                    continue
                timing = cj_def.get('timing', 'fixed')
                defaults = {}
                if timing == 'hourly':
                    minute = self.data.get(f'minute_{cj_def["id"]}')
                    defaults['minute'] = int(minute) if minute else self.app.port % 60
                elif timing == 'daily':
                    hour = self.data.get(f'hour_{cj_def["id"]}')
                    minute = self.data.get(f'minute_{cj_def["id"]}')
                    defaults['hour'] = int(hour) if hour else cj_def.get('default_hour', 23)
                    defaults['minute'] = int(minute) if minute else cj_def.get('default_minute', 0)
                AppCronjob.objects.update_or_create(
                    app=self.app,
                    cronjob_id=cj_def['id'],
                    defaults=defaults
                )
