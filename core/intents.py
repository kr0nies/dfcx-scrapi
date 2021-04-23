import logging
import pandas as pd
import requests
import google.cloud.dialogflowcx_v3beta1.services as services
import google.cloud.dialogflowcx_v3beta1.types as types
from collections import defaultdict
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.protobuf import field_mask_pb2

from typing import Dict, List

# logging config
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

SCOPES = ['https://www.googleapis.com/auth/cloud-platform',
          'https://www.googleapis.com/auth/dialogflow']


class Intents:
    def __init__(self, creds_path: str, intent_id: str = None):
        self.creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES)
        self.creds.refresh(Request())  # used for REST API calls
        self.token = self.creds.token  # used for REST API calls

        if intent_id:
            self.intent_id = intent_id
            self.client_options = self._set_region(self.intent_id)

    @staticmethod
    def _set_region(item_id):
        """different regions have different API endpoints

        Args:
            item_id: agent/flow/page - any type of long path id like
                `projects/<GCP PROJECT ID>/locations/<LOCATION ID>

        Returns:
            client_options: use when instantiating other library client objects
        """
        try:
            location = item_id.split('/')[3]
        except IndexError as err:
            logging.error('IndexError - path too short? %s', item_id)
            raise err

        if location != 'global':
            api_endpoint = '{}-dialogflow.googleapis.com:443'.format(location)
            client_options = {'api_endpoint': api_endpoint}
            return client_options

        else:
            return None  # explicit None return when not required

    @staticmethod
    def _set_api_options(self, id_item):
        '''bundle API parameters'''
        client_options = self._set_region(id_item)
        return {
            'client_options': client_options,
            'credentials': self.creds
        }

    def get_intents_map(self, agent_id, reverse=False):
        """ Exports Agent Intent Names and UUIDs into a user friendly dict.

        Args:
          - agent_id, the formatted CX Agent ID to use
          - reverse, (Optional) Boolean flag to swap key:value -> value:key

        Returns:
          - intents_map, Dictionary containing Intent UUIDs as keys and
              intent.display_name as values
          """

        if reverse:
            intents_dict = {intent.display_name: intent.name
                            for intent in self.list_intents(agent_id)}

        else:
            intents_dict = {intent.name: intent.display_name
                            for intent in self.list_intents(agent_id)}

        return intents_dict

    def list_intents(self, agent_id):
        '''provide a list of intents'''
        request = types.intent.ListIntentsRequest()
        request.parent = agent_id

        client_options = self._set_region(agent_id)
        client = services.intents.IntentsClient(
            credentials=self.creds,
            client_options=client_options)
        response = client.list_intents(request)

        intents = []
        # pager through the response, not CX 'pages'
        for page in response.pages:
            for intent in page.intents:
                intents.append(intent)

        return intents

    def get_intent(self, intent_id):
        client_options = self._set_region(intent_id)
        client = services.intents.IntentsClient(
            credentials=self.creds, client_options=client_options)
        response = client.get_intent(name=intent_id)

        return response

    def create_intent(self, agent_id, obj=None, **kwargs):
        # If intent_obj is given, set intent variable to it
        if obj:
            intent = obj
            intent.name = ''
        else:
            intent = types.intent.Intent()

        # Set optional arguments as intent attributes
        for key, value in kwargs.items():
            if key == 'training_phrases':
                assert isinstance(kwargs[key], list)
                training_phrases = []
                for x in kwargs[key]:
                    if isinstance(x, dict):
                        tp = types.intent.Intent.TrainingPhrase()
                        parts = []
                        for y in x['parts']:
                            if isinstance(y, dict):
                                part = types.intent.Intent.TrainingPhrase.Part()
                                part.text = y['text']
                                part.parameter_id = y.get('parameter_id')
                                parts.append(part)
                            else:
                                print("Wrong object in parts list")
                                return
                        tp.parts = parts
                        tp.repeat_count = x.get("repeat_count")
                        training_phrases.append(tp)
                    else:
                        print("Wrong object in training phrases list")
                        return
                setattr(intent, key, training_phrases)
            setattr(intent, key, value)

        client_options = self._set_region(agent_id)
        client = services.intents.IntentsClient(
            client_options=client_options, credentials=self.creds)
        response = client.create_intent(parent=agent_id, intent=intent)

        return response

    def update_intent(self, intent_id, obj=None, **kwargs):
        """ Updates a single Intent object based on provided args.

        Args:
          intent_id, the destination Intent ID. Must be formatted properly
              for Intent IDs in CX.
          obj, The CX Intent object in proper format. This can also
              be extracted by using the get_intent() method.
        """
        if obj:
            intent = obj
            intent.name = intent_id
        else:
            intent = self.get_intent(intent_id)

        logging.info('dfcx_lib update intent %s', intent_id)

        client_options = self._set_region(intent_id)
        client = services.intents.IntentsClient(
            client_options=client_options,
            credentials=self.creds)
        response = client.update_intent(intent=intent)

        return response

    def delete_intent(self, intent_id, obj=None):
        if obj:
            intent_id = obj.name
        else:
            client_options = self._set_region(intent_id)
            client = services.intents.IntentsClient(
                client_options=client_options)
            client.delete_intent(name=intent_id)

def intents_to_dataframe(self, intents):
        """
        This functions takes an Intents object from the DFCX API and returns
        a Pandas Dataframe
        """
        intent_dict = defaultdict(list)

        for element in intents:
            if 'training_phrases' in element:
                for tp in element.training_phrases:
                    s = []
                    if len(tp.parts) > 1:
                        for item in tp.parts:
                            s.append(item.text)
                        intent_dict[element.display_name].append(''.join(s))
                    else:
                        intent_dict[element.display_name].append(
                            tp.parts[0].text)
            else:
                intent_dict[element.display_name].append('')

        df = pd.DataFrame.from_dict(intent_dict, orient='index').transpose()
        df = df.stack().to_frame().reset_index(level=1)
        df = df.rename(
            columns={
                'level_1': 'intent',
                0: 'tp'}).reset_index(
            drop=True)
        df = df.sort_values(['intent', 'tp'])

        return df