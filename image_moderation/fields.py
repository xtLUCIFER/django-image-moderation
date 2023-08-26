"""
Model fields for image moderation
"""
import boto3
from django.db import models
from django.db.models import F
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.apps import apps
from django.http import HttpRequest
from userprofile.middleware import get_user



_moderation_levels = {
    0: [],
    1: [
        'Visually Disturbing',
    ],
    2: [
        'Explicit Nudity',
        'Visually Disturbing',
        'Violence',
    ],
    3: [
        'Explicit Nudity',
        'Violence',
        'Visually Disturbing',
        'Gambling',
        'Hate Symbols',
    ],
    4: [
        'Explicit Nudity',
        'Suggestive',
        'Violence',
        'Visually Disturbing',
        'Rude Gestures',
        'Drugs',
        'Tobacco',
        'Alcohol',
        'Gambling',
        'Hate Symbols',
    ],
}


class ImageModerationField(models.ImageField):
    """
    Django Image Field child that adds
    image moderation functionality

    Must have IMAGE_MODERATION attribute in django project settings
    that should be a dictionary with AWS credentials
    """
    def __init__(
            self,
            moderation_level=4,
            min_confidence=60,
            custom_labels=None,
            not_appropiate_text=_('The content of this image is not suitable. Uploading such material could have a negative impact on your profile. Repeated violations may lead to permanent profile suspension.'),
            **kwargs,
        ):
        self.moderation_level = moderation_level
        self.custom_labels = custom_labels
        self.min_confidence = min_confidence
        self.not_appropiate_text = not_appropiate_text
        super().__init__(**kwargs)

    def moderate_image(self, image):
        is_appropriate = True
        moderation_settings = getattr(settings, 'IMAGE_MODERATION')
        access_key = moderation_settings['AWS_ACCESS_KEY']
        secret_key = moderation_settings['AWS_SECRET_KEY']

        client = boto3.client(
            'rekognition',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='us-east-1'
        )

        response = client.detect_moderation_labels(
            Image={
                'Bytes': image.read()
            }
        )

        print(response)

        moderation_labels = response.get('ModerationLabels', [])
        moderation_model_version = response.get('ModerationModelVersion', '')

        # Define comparison_labels based on your logic
        if self.custom_labels is not None:
            comparison_labels = self.custom_labels
        else:
            comparison_labels = _moderation_levels.get(
                self.moderation_level,
                _moderation_levels[4]
            )

        moderation_details = []
        for label in moderation_labels:
            label_data = {
                'Name': label['Name'],
                'Confidence': label['Confidence'],
                'ParentName': label['ParentName']
            }
            moderation_details.append(label_data)

            if (
                label['Name'] in comparison_labels and
                label['Confidence'] > self.min_confidence
            ):
                is_appropriate = False

        result = {
            'ModerationLabels': moderation_details,
            'ModerationModelVersion': moderation_model_version
        }

        return is_appropriate, {'moderation_details': result}




    

    def validate(self, value, model_instance, **kwargs):
        
        is_appropriate, moderation_result = self.moderate_image(value)


        if not is_appropriate:
            userr = get_user()
            moderation_details = moderation_result['moderation_details']
            
            # Get the model class using the apps module
            explicit_content_model = apps.get_model('userprofile', 'ExplicitContent')
            
            # Get the current warning count from the model instance
            current_warning_count = getattr(model_instance, 'warning_count', 0)
            
            explicit_content = explicit_content_model(
                user=userr,
                image=value,
                moderation_lables=moderation_details,
                warning_count=current_warning_count + 1  
            )
            explicit_content.save()
            
            # Raise a ValidationError with a custom error message
            raise ValidationError(self.not_appropiate_text)
        super().validate(value, model_instance, **kwargs)

        