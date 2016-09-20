from Acquisition import aq_base
from BeautifulSoup import BeautifulSoup
from DateTime import DateTime
from Products.CMFCore.utils import getToolByName
from Products.Five import BrowserView
from plone.namedfile.file import NamedBlobFile
from agsci.leadimage.content.behaviors import LeadImage
from decimal import Decimal
from datetime import datetime
from zope.interface import implements
from zope.publisher.interfaces import IPublishTraverse

import Missing
import dicttoxml
import json
import re
import urllib2
import urlparse

from agsci.atlas.utilities import toISO, encode_blob

# Custom Atlas Schemas
from agsci.atlas.content import atlas_schemas
from agsci.atlas.content.behaviors import IAtlasMetadata
from agsci.atlas.content.event.cvent import ICventEvent
from agsci.atlas.content.publication import IPublication

# Prevent debug messages in log
dicttoxml.set_debug(False)

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

class BaseView(BrowserView):

    implements(IPublishTraverse)

    data_format = None
    valid_data_formats = ['json', 'xml']
    default_data_format = 'xml'

    # Default window for listing updated items
    default_updated = 3600

    # Check if we've been passed an `updated` URL parameter.
    # Returns default value of `default_updated` if a non-numeric value is
    # passed.  Otherwise, defaults to None
    def getUpdated(self):
        v = self.request.get('updated', None)

        if v:

            # Cast 'updated' parameter to an integer, using the default above
            # if this fails
            try:
                v = int(v)
            except ValueError:
                v = self.default_updated

            return (DateTime() - (v/86400.0))

        return None

    # Check if we've been passed an `updated_min` and/or an `updated_max`
    # URL parameter.
    # Returns a range tuple (min,max) if they're present.
    # Otherwise, defaults to None
    def getUpdatedRange(self):

        # Get URL parameters
        v_min = self.request.get('updated_min', None)
        v_max = self.request.get('updated_max', None)

        # If no parameters were passed in, return None
        if not (v_min or v_max):
            return None

        # Set defaults
        v_min_default = DateTime(0) # Unix epoch
        v_max_default = DateTime() # Now

        # If there's not a v_min parameter, set it to the default
        # Otherwise, try to make it into a DateTime()
        # If that fails, set it to the default
        if not v_min:
            v_min = v_min_default

        else:
            try:
                v_min = DateTime(v_min)
            except SyntaxError:
                v_min = v_min_default

        # Do the same for v_max
        if not v_max:
            v_max = v_max_default
        else:
            try:
                v_max = DateTime(v_max)
            except SyntaxError:
                v_max = v_max_default

        # Return the range tuple
        return (v_min, v_max)

    # Calculate last modified date criteria based on URL parameters
    # Returns a `dict` with a range and query keys.
    def getModifiedCriteria(self):

        updated_seconds_ago = self.getUpdated()

        if updated_seconds_ago:
            return {'range' : 'min', 'query' : updated_seconds_ago}

        updated_range = self.getUpdatedRange()

        if updated_range:
            return {'range' : 'min:max', 'query' : updated_range}

        return None

    # Check if we're recursive based on URL parameter
    # Defaults to True
    @property
    def isRecursive(self):
        v = self.request.form.get('recursive', 'True')
        return not (v.lower() in ('false', '0'))

    # Check if we're showing binary data
    # Defaults to True
    @property
    def showBinaryData(self):
        v = self.request.form.get('bin', 'True')
        return not (v.lower() in ('false', '0'))

    def getDataFormat(self):

        if self.data_format and self.data_format in self.valid_data_formats:
            return self.data_format

        return self.default_data_format

    # Pull format from view name, defaulting to JSON
    def publishTraverse(self, request, name):
        if name and name in self.valid_data_formats:
            self.data_format = name

        return self

    # http://stackoverflow.com/questions/1175208/elegant-python-function-to-convert-camelcase-to-camel-case
    def format_key(self, name):
        s1 = first_cap_re.sub(r'\1_\2', name)
        return all_cap_re.sub(r'\1_\2', s1).lower()

    @property
    def portal_catalog(self):
        return getToolByName(self.context, 'portal_catalog')

    def html_to_text(self, html):
        portal_transforms = getToolByName(self.context, 'portal_transforms')
        text = portal_transforms.convert('html_to_text', html).getData()
        return text

    def getMetadata(self):
        try:
            m = self.portal_catalog.getMetadataForUID("/".join(self.context.getPhysicalPath()))
        except:
            return {} # Return an empty dict if there's an issue with the catalog

        for i in m.keys():
            if m[i] == Missing.Value:
                m[i] = ''

        return m

    def getIndexData(self):
        try:
            return self.portal_catalog.getIndexDataForUID("/".join(self.context.getPhysicalPath()))
        except:
            return {} # Return an empty dict if there's an issue with the catalog

    def getCatalogData(self):
        data = self.getMetadata()
        indexdata = self.getIndexData()

        for i in indexdata.keys():
            if not data.has_key(i):
                data[i] = indexdata[i]

        return self.fixData(data)

    def fixData(self, data):

        # Normalize keys to 'x_y_z' format
        data = self.normalize_keys(data)

        # Fix any value datatype issues
        data = self.fix_value_datatypes(data)

        # Exclude unused fields
        data = self.exclude_unused_fields(data)

        # Exclude empty non-required fields
        data = self.remove_empty_nonrequired_fields(data)

        return data

    def exclude_unused_fields(self, data):

        # Remove excluded fields

        exclude_fields = [
            'allowedRolesAndUsers',
            'author_name',
            'cmf_uid',
            'commentators',
            'created',
            'Creator',
            'CreationDate',
            'Date',
            'EffectiveDate',
            'effectiveRange',
            'ExpirationDate',
            'excludeFromNav',
            'isFolderish',
            'getCommitteeNames',
            'getDepartmentNames',
            'getIcon',
            'getObjPositionInParent',
            'getObjSize',
            'getRawClassifications',
            'getRawCommittees',
            'getRawDepartments',
            'getRawPeople',
            'getRawRelatedItems',
            'getRawSpecialties',
            'getResearchTopics',
            'getSortableName',
            'getSpecialtyNames',
            'id',
            'in_reply_to',
            'in_response_to',
            'last_comment_date',
            'listCreators',
            'listContributors',
            'meta_type',
            'ModificationDate',
            'object_provides',
            'portal_type',
            'path',
            'SearchableText',
            'sortable_title',
            'total_comments',
            'sync_uid',
            'atlas_category_level_1',
            'atlas_category_level_2',
            'atlas_category_level_3',
            'atlas_curriculum',
            'atlas_program_team',
            'atlas_state_extension_team',
        ]

        for i in exclude_fields:
            _i = self.format_key(i)

            if data.has_key(_i):
                del data[_i]

        return data

    def normalize_keys(self, data):

        # Ensure keys from catalog indexes/metadata are non-camel case lowercase
        for k in data.keys():
            _k = self.format_key(k)
            _k = self.rename_key(_k)

            if k != _k:
                data[_k] = data[k]
                del data[k]

        return data

    def rename_key(self, i):

        # Rename keys to match Magento import fields
        rename_keys = [
            ('UID' , 'plone_id'),
            ('Title' , 'name'),
            ('Description' , 'short_description'),
            ('modified' , 'updated_at'),
            ('effective' , 'publish_date'),
            ('expires' , 'product_expiration'),
            ('Type' , 'product_type'),
            ('getId', 'short_name'),
            ('review_state', 'plone_status'),
            ('getRemoteUrl', 'remote_url'),
            ('username', 'person_psu_user_id'),
            ('start', 'event_start_date'),
            ('end', 'event_end_date'),
            ('agenda', 'event_agenda'),
            ('contact_email', 'email_address'),
            ('email', 'email_address'),
            ('street_address', 'address'),
            ('zip_code', 'zip'),
            ('phone_number', 'phone'),
            ('fax_number', 'fax'),
            ('bio', 'description'),
            ('job_titles', 'person_job_titles'),
            ('classifications', 'person_classification'),
            ('areas_expertise', 'expertise'),
            ('primary_profile_url', 'educator_primary_profile_url'),
            ('registration_help_name', 'event_registration_help_name'),
            ('registration_help_phone', 'event_registration_help_phone'),
            ('registration_help_email', 'event_registration_help_email'),
            ('registrant_status', 'event_registrant_status'),
            ('registrant_type', 'event_registrant_type'),
            ('registration_status', 'event_registration_status'),
            ('capacity', 'event_capacity'),
            ('walkin', 'event_walkin'),
            ('cancellation_deadline', 'cancelation_deadline'),  # Misspelled per http://grammarist.com/spelling/cancel/
        ]

        # Make dict out of key/value tuples
        rename_keys = dict([(self.format_key(j), k) for (j,k) in rename_keys])

        # Resolve explicitly renamed field into `v`, if it exists
        v = rename_keys.get(i, i)

        # Implicitly strip 'atlas_' from the beginning of any keys to simplify
        # the list of renamed keys
        for j in ['atlas_']:
            if v.startswith(j):
                v = v[len(j):]

        # Return the renamed value
        return v


    def fix_value_datatypes(self, data):

        for (k,v) in data.iteritems():

            # If we're a datetime, convert to DateTime and use the ISO representation string
            if isinstance(v, datetime):
                data[k] = toISO(DateTime(data[k]))

            # If we're a DateTime, use the ISO representation string
            elif isinstance(v, DateTime):
                data[k] = toISO(data[k])

            # Convert decimal to string with two decimal places.
            elif isinstance(v, Decimal):
                data[k] = '%0.2f' % v

            # XML type logic sees `zope.i18nmessageid.message.Message` as a list
            # and returns the type one letter at a time as a list.
            elif type(v).__name__ == 'Message':
                data[k] = unicode(v)

            # If this is a file, add additional mimetype info
            elif isinstance(v, NamedBlobFile):
                (file_mimetype, file_data) = encode_blob(v, self.showBinaryData)

                data[k] = {
                    'data' : file_data,
                    'mimetype' : file_mimetype,
                }

            # If this is a list, iterate through all the items and check if it's
            # a dict.  If it's a dict, run this routine on that dict.
            elif isinstance(v, list):

                for i in range(0, len(v)):
                    if isinstance(v[i], dict):
                        v[i] = self.fix_value_datatypes(v[i])

            # If it's a dict, run this routine on that dict.
            elif isinstance(v, dict):
                data[k] = self.fix_value_datatypes(data[k])

        return data

    def remove_empty_nonrequired_fields(self, data):

        # Listing of required fields
        required_fields = ['Title', 'available_to_public']

        # Normalize
        required_fields = [self.format_key(x) for x in required_fields]

        for k in data.keys():
            if k not in required_fields:
                if not data[k]:
                    del data[k]

        return data

    # Determine if we have a product, based on if we have the metadata
    # assigned to it.
    def isProduct(self):
        return IAtlasMetadata.providedBy(self.context)

    # Takes a list of variable-length tuples, and condenses that into the
    # minimum set necessary to prevent duplication.  For example:
    #
    # (X,Y),
    # (X,Y,Z),
    #
    # is minimized to:
    #
    # (X,Y,Z),
    #
    # Not sure if this is required?
    #
    def minimizeStructure(self, c, keys=[]):
        if c:
            lengths = map(lambda x:len(x), c)
            min_items =  min(lengths)
            max_items =  max(lengths)

            if max_items > min_items:
                for i in range(min_items,max_items):
                    base_items = filter(lambda x: len(x) == i, c)
                    base_items_plus = filter(lambda x: len(x) > i, c)
                    base_items_plus_adjusted = map(lambda x: tuple(x[0:i]), base_items_plus)
                    for j in set(base_items_plus_adjusted) & set(base_items):
                        c.remove(j)

        # If a list of key names are provided, map back into a dict structure
        # with the key name as the key, and the positional item in the list as
        # a value.
        if keys:

            def toDict(x):
                return dict(zip(keys, x))

            return map(toDict, c)

        return c

    def getData(self):

        # Pull data from catalog
        data = self.getCatalogData()

        sd = self.getSchemaData()

        data.update(sd)

        if self.isProduct():

            # Set `product_platform` default
            data['product_platform'] = 'Plone'

            # Set `product_platform` and `product_type` if we're a Cvent event
            if ICventEvent.providedBy(self.context):
                data['product_platform'] = 'Cvent'
                data['product_type'] = getattr(self.context, 'atlas_event_type', 'Workshop')

            # Set `product_platform` if we're a Publication
            elif IPublication.providedBy(self.context):
                data['product_platform'] = 'Salesforce'

            # Magento Status-es
            data['visibility'] = 'Catalog, Search'

            # Populate Category Level 1/2/3
            category_level_keys = ['category_level%d' % x for x in range(1,4)]

            categories = []

            for i in category_level_keys:
                j = data.get(i, [])

                for k in j:
                    categories.append(tuple(k.split(':')))

                if j:
                    del data[i]

            data['categories'] = self.minimizeStructure(categories)

            # Populate Extension Structure Information
            extension_structure_keys = ['state_extension_team', 'program_team', 'curriculum']

            extension_structure = []

            for i in extension_structure_keys:
                j = data.get(i, [])

                for k in j:
                    extension_structure.append(tuple(k.split(':')))

                if j:
                    del data[i]

            data['extension_structure'] = self.minimizeStructure(extension_structure, keys=extension_structure_keys)

            # Populate people information

            # Assign primary contact id to first id in owners
            if data.get('owners', []):
                data['primary_contact_psu_user_id'] = data.get('owners')[0]

            # Object URL
            url = self.context.absolute_url()
            data['external_url'] = url

            # Handle binary data fields by either encoding them base64, or removing them

            # If we DO show binary data
            if self.showBinaryData:

                # Lead Image
                if data.get('has_lead_image', False):
                    img_field_name = 'leadimage'
                    img_field = getattr(self.context, img_field_name, None)

                    (img_mimetype, img_data) = encode_blob(img_field, self.showBinaryData)

                    if img_data:
                        data['leadimage'] = {
                            'data' : img_data,
                            'mimetype' : img_mimetype,
                            'caption' : LeadImage(self.context).leadimage_caption,
                        }

                # File Field
                if data.get('file', None) and self.showBinaryData:
                    file_field_name = 'file'
                    file_field = getattr(self.context, file_field_name, None)

                    (file_mimetype, file_data) = encode_blob(file_field, self.showBinaryData)

                    if file_data:
                        data['file'] = {
                            'data' : file_data,
                            'mimetype' : file_mimetype,
                        }

            # If we DO NOT show binary data
            else:
                for i in ['file', 'image', 'leadimage']:
                    if data.has_key(i):
                        del data[i]

        else:
            # Remove all the product fields for non-products
            for k in ('publish_date', 'product_expiration', 'updated_at',
                      'plone_status', 'language', 'authors', 'owners'):
                if data.has_key(k):
                    del data[k]

        # Body text
        if hasattr(self.context, 'text') and hasattr(self.context.text, 'raw'):
            data['description'] = self.context.text.raw

        return data

    def getJSON(self):
        return json.dumps(self.getData(), indent=4, sort_keys=True)

    def getXML(self):
        return dicttoxml.dicttoxml(self.getData(), custom_root='item')

    def __call__(self):

        data_format = self.getDataFormat()

        # Set headers to prevent caching
        self.request.response.setHeader('Pragma', 'no-cache')
        self.request.response.setHeader('Cache-Control', 'private, no-cache, no-store')

        # Pass back JSON or XML data, while setting request header.
        if data_format == 'json':
            json = self.getJSON()
            self.request.response.setHeader('Content-Type', 'application/json')
            return json

        elif data_format == 'xml':
            xml = self.getXML()
            self.request.response.setHeader('Content-Type', 'application/xml')
            return xml

    # Handle HEAD request so testing the connection in Jitterbit doesn't fail
    # From plone.namedfile.scaling
    def HEAD(self, REQUEST, RESPONSE=None):
        return ''

    HEAD.__roles__ = ('Anonymous',)

    def getSchemaData(self, schemas=[], fields=[]):
        data = {}

        # Use the Atlas products schema if a schema is not passed in
        if not schemas:
            schemas.extend(atlas_schemas)

        # Attach all custom fields from schema
        for i in schemas:
            if i.providedBy(self.context):
                fields.extend(i.names())

        for i in set(fields):

            # Ref:
            # http://stackoverflow.com/questions/9790991/why-is-getattr-so-much-slower-than-self-dict-get
            # The line below replaces:
            # v = getattr(self.context, i, None)
            # which took substantially longer (e.g. 8 seconds vs 2.5 minutes)
            # when processing 300+ items in a folder.  Since the Dexterity
            # schema fields appear to be stored as local attributes, this should
            # not cause problems. However, if it does, we can revert to the
            # original behavior, or do so selectively.

            v = self.context.__dict__.get(i, None)

            # If it's a text field
            if hasattr(v, 'raw'):
                v = v.raw

            # Handle values, if they exist
            if v:

                # Filter out blank list items
                if isinstance(v, (list, tuple,)):
                    v = [x for x in v if x]

                data[i] = v

        data = self.fixData(data)

        return data

class BaseContainerView(BaseView):

    def getContents(self):
        return self.context.listFolderContents()

    def getData(self):
        data = super(BaseContainerView, self).getData()

        if self.isRecursive:
            contents = self.getContents()

            if contents:
                data['contents'] = []

                for o in contents:

                    api_data = o.restrictedTraverse('@@api')

                    data['contents'].append(api_data.getData())

        return data

def getAPIData(object_url):

    # Grab JSON data
    json_url = '%s/@@api/json' % object_url

    try:
        json_data = urllib2.urlopen(json_url).read()
    except urllib2.HTTPError:
        raise ValueError("Error accessing object, url: %s" % json_url)

    # Convert JSON to Python structure
    try:
        data = json.loads(json_data)
    except ValueError:
        raise ValueError("Error decoding json: %s" % json_url)

    return data
