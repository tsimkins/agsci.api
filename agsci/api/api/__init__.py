from Acquisition import aq_base
from BeautifulSoup import BeautifulSoup
from DateTime import DateTime
from Products.CMFCore.utils import getToolByName
from Products.Five import BrowserView
from plone.namedfile.file import NamedBlobFile
from agsci.leadimage.content.behaviors import LeadImage
from decimal import Decimal
from datetime import datetime
from plone.autoform.interfaces import IFormFieldProvider
from zope.component import getAdapters
from zope.interface import implements
from zope.publisher.interfaces import IPublishTraverse

import Missing
import dicttoxml
import json
import re
import urllib2
import urlparse

from agsci.atlas.content.behaviors import IShadowProduct, ISubProduct
from agsci.atlas.utilities import toISO, encode_blob, getAllSchemaFields, getBaseSchema

# Custom Atlas Schemas
from agsci.atlas.content import atlas_schemas, DELIMITER, IAtlasProduct
from agsci.atlas.content.behaviors import IAtlasInternalMetadata, \
     IAtlasProductCategoryMetadata, IAtlasProductAttributeMetadata
from agsci.atlas.content.event.cvent import ICventEvent
from agsci.atlas.content.publication import IPublication

from ..interfaces import IAPIDataAdapter

# Explicit delete value
class DeleteValue(object):
    pass

DELETE_VALUE = DeleteValue()

# Prevent debug messages in log
dicttoxml.set_debug(False)

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

class BaseView(BrowserView):

    implements(IPublishTraverse)

    data_format = None
    valid_data_formats = ['json', 'xml']
    default_data_format = 'xml'

    show_all_fields = False

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
            # Initialize all index values as blank
            data = dict([(x, '') for x in self.portal_catalog.indexes()])

            # Update with actual values
            data.update(
                self.portal_catalog.getIndexDataForUID("/".join(self.context.getPhysicalPath()))
                )

            # Return listing
            return data
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
            'category_level_1',
            'category_level_2',
            'category_level_3',
            'atlas_curriculum',
            'atlas_program_team',
            'atlas_state_extension_team',
            'content_error_codes',
            'content_issues',
            'registration_fieldsets',
            'IsChildProduct',
            'leadimage_show',
        ]

        if not self.isProduct():
            exclude_fields.extend([
                    'program_team',
                    'state_extension_team',
                    'curriculum',
                ]
            )

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
            ('Type' , 'plone_product_type'),
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
            ('store_view_id', 'website_ids'),
            ('pdf_file', 'pdf'),
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

        # Bypass this if show_all_fields is True
        if not self.show_all_fields:

            # Listing of required fields
            required_fields = ['Title', 'available_to_public']

            # Normalize
            required_fields = [self.format_key(x) for x in required_fields]

            for k in data.keys():
                if k not in required_fields:

                    # If it's not a boolean value, and an empty value, delete it.
                    if not isinstance(data[k], bool) and not data[k]:
                        del data[k]

        return data

    # Determine if we have a product, based on if we have the metadata
    # assigned to it.
    def isProduct(self):

        for _interface in [ IAtlasProduct, IAtlasInternalMetadata,
                            IAtlasProductCategoryMetadata,
                            IAtlasProductAttributeMetadata]:

            if _interface.providedBy(self.context):
                return True

        return False

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

    # Given a Plone product type, return the expected Magento product type
    def mapProductType(self, data):

        # Return dict with which to update data
        _data = {}

        # Mapping for attribute set in Magento
        attribute_set_mapping = {
            'App' : 'APPs',
            'Article' : 'Article',
            'Conference' : 'Workshop Complex',
            'Conference Group' : 'Workshop Complex',
            'Curriculum' : 'Curriculum',
            'Learn Now Video' : 'Video Free',
            'News Item' : 'News',
            'Online Course' : 'Online Course',
            'Online Course Group' : 'Online Course',
            'Person' : 'Person',
            'Publication Group' : 'Publication',
            'Publication Print' : 'Publication',
            'Publication Digital' : 'Publication',
            'Publication Bundle' : 'Publication',
            'Smart Sheet' : 'Smart Sheets',
            'Webinar' : 'Webinar',
            'Webinar Group' : 'Webinar',
            'Workshop' : 'Workshop Simple',
            'Workshop Group' : 'Workshop Complex'
        }

        # Education format mapping (for filter in Magento)
        education_format_mapping = {
            'App' : 'Downloadable',
            'Article' : 'Articles',
            'Conference' : 'Conferences',
            'Conference Group' : 'Conferences',
            'Curriculum' : 'Curricula',
            'Learn Now Video' : 'Videos',
            'News Item' : 'News',
            'Online Course' : 'Online Courses',
            'Online Course Group' : 'Online Courses',
            'Person' : 'Educators',
            'Publication Group' : 'Guides and Publications',
            'Publication Print' : 'Guides and Publications',
            'Publication Digital' : 'Guides and Publications',
            'Publication Bundle' : 'Guides and Publications',
            'Smart Sheet' : 'Downloadable',
            'Webinar' : 'Webinars',
            'Webinar Group' : 'Webinars',
            'Workshop' : 'Workshops',
            'Workshop Group' : 'Workshops'
        }

        # Mapping of Plone product type to integration produc type
        product_type_mapping = {
            'App' : 'App',
            'Article' : 'Article',
            'Conference' : 'Conference',
            'Conference Group' : 'Conference Group',
            'Curriculum' : 'Curriculum',
            'Cvent Event' : 'Cvent Event',
            'Learn Now Video' : 'Video',
            'News Item' : 'News',
            'Online Course' : 'Online Course',
            'Online Course Group' : 'Online Course Group',
            'Person' : 'Person',
            'Publication Group' : 'Publication Group',
            'Publication Print' : 'Publication Print',
            'Publication Digital' : 'Publication Digital',
            'Publication Bundle' : 'Publication Bundle',
            'Smart Sheet' : 'Smart Sheet',
            'Webinar' : 'Webinar',
            'Webinar Group' : 'Webinar Group',
            'Workshop' : 'Workshop',
            'Workshop Group' : 'Workshop Group'
        }

        # One-off for Cvent events.  Event Type (manually set) to
        # `attribute_set` and `education_format`
        cvent_event_type_mapping = {
            'Workshop' : {
                'attribute_set' : 'Workshop Complex',
                'education_format' : 'Workshops',
            },
            'Webinar' : {
                'attribute_set' : 'Webinar',
                'education_format' : 'Webinars',
            },
            'Conference' : {
                'attribute_set' : 'Workshop Complex',
                'education_format' : 'Conferences',
            },
        }

        # Get the `product_type` value from the input data
        plone_product_type = data.get('plone_product_type', None)

        # If the `product_type` value exists, and is not null
        if plone_product_type:

            # Attribute Set
            _data['attribute_set'] = attribute_set_mapping.get(plone_product_type, None)

            # Education Format (Filter)
            _data['education_format'] = education_format_mapping.get(plone_product_type, None)

            # Product Type (Integration)
            # Note that, unlike the other mappings, this one defaults to `plone_product_type`
            _data['product_type'] = product_type_mapping.get(plone_product_type, plone_product_type)

            # Set `product_platform` default
            data['product_platform'] = 'Plone'

            # Calculate/update fields if we're a Cvent event
            if ICventEvent.providedBy(self.context):

                # Set `product_platform`
                data['product_platform'] = 'Cvent'

                # Calculate `attribute_set` and `education_format`
                # based on the Event Type attribute of the Cvent event
                event_type = getattr(self.context, 'atlas_event_type', 'Workshop')

                # Update data fields
                _data.update(cvent_event_type_mapping.get(event_type, {}))

            # Set `product_platform` if we're a Publication
            elif IPublication.providedBy(self.context):
                data['product_platform'] = 'Salesforce'

        return _data

    def getData(self, subproduct=True):

        # Pull data from catalog
        data = self.getCatalogData()

        # Schema data
        sd = self.getSchemaData()
        data.update(sd)

        # Adapter data
        adapter_data = self.getAdapterData()
        data.update(adapter_data)

        if self.isProduct():

            # Magento Visibility.  Provide default if not already set.
            if not data.has_key('visibility'):
                data['visibility'] = 'Catalog, Search'

            # Map product type to what Magento expects
            data.update(self.mapProductType(data))

            # Populate Category Level 1/2/3
            category_level_keys = ['category_level%d' % x for x in range(1,4)]

            categories = []

            for i in category_level_keys:
                j = data.get(i, [])

                for k in j:
                    categories.append(tuple(k.split(DELIMITER)))

                if j:
                    del data[i]

            data['categories'] = self.minimizeStructure(categories)

            # Populate Extension Structure Information
            extension_structure_keys = ['state_extension_team', 'program_team', 'curriculum']

            extension_structure = []

            for i in extension_structure_keys:
                j = data.get(i, [])

                if j:
                    for k in j:
                        extension_structure.append(tuple(k.split(DELIMITER)))

                    del data[i]

            data['extension_structure'] = self.minimizeStructure(extension_structure, keys=extension_structure_keys)

            # Populate people information

            # Assign primary contact id to first id in owners
            if data.get('owners', []):
                data['primary_contact_psu_user_id'] = data.get('owners')[0]

            # Object URL
            url = self.context.absolute_url()
            data['plone_url'] = url
            data['api_url_xml'] = '%s/@@api' % url
            data['api_url_json'] = '%s/@@api/json' % url

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
                for i in ['file', 'image', 'leadimage', 'pdf']:
                    if data.has_key(i):
                        del data[i]

            # Include subproduct data (default yes, but getSubProductData() calls
            # getData() with a subproduct=False to prevent infinite recursion.
            if subproduct:

                subproduct_data = self.getSubProductData()

                if subproduct_data:
                    if not data.has_key("contents"):
                        data['contents'] = []

                    data['contents'].extend(subproduct_data)

        else:
            # If we're not a Product, copy the value for `plone_product_type`
            # into `product_type` for the integration.
            data['product_type'] = data['plone_product_type']

            # Remove all the product fields for non-products
            for k in ('publish_date', 'product_expiration', 'updated_at',
                      'plone_status', 'language', 'authors', 'owners'):
                if data.has_key(k):
                    del data[k]

        # Body text
        if hasattr(self.context, 'text') and hasattr(self.context.text, 'raw'):
            data['description'] = self.context.text.raw

        # Delete explicitly delete
        data = self.clearDeletedValues(data)

        return data

    def clearDeletedValues(self, data):
        # Delete explicitly delete
        for _k in data.keys():
            if isinstance(data[_k], DeleteValue):
                del data[_k]

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

    def getSchemaData(self, **kwargs):
        # Data to return
        data = {}

        # Data fields and schemas to look at. For some reason, using named
        # parameters (e.g. "fields=[]") resulted in values being provided
        # without having them being passed in.
        fields = kwargs.get('fields', [])
        schemas = kwargs.get('schemas', [])

        # Use the Atlas products schema if a schema is not passed in. Use
        # inherited schemas as well.
        if not schemas:

            # Base schema
            schemas.append(
                getBaseSchema(self.context)
            )

            # Atlas schemas
            schemas.extend(atlas_schemas)

        # Attach all custom fields from schema
        for i in set(schemas):

            # Only include schemas that provide form fields.
            if IFormFieldProvider.providedBy(i):
                if i.providedBy(self.context):
                    fields.extend(getAllSchemaFields(i))

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

            # Update 2016-10-27: Added the getattr() as a fallback, because it
            # appears that Dexterity fields left as a default aren't returned.
            # This doesn't seem to have a significant performance impact, and
            # it returns the "right" value.

            v = self.context.__dict__.get(i,
                    getattr(self.context, i, None)
                )

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

    def getAdapterData(self):

        data = {}

        # Iterate through all of the adapters that provided `IAPIDataAdapter`
        # and include the output of 'getData' in the API output.
        #
        # This is a little cleaner than doing stuff in the @@api subclassed views

        for (name, adapted) in getAdapters((self.context,), IAPIDataAdapter):
            try:
                # Pull the 'getData()' values, and update the API data
                ad = adapted.getData(bin=self.showBinaryData)
            except AttributeError:
                # If there's no 'getData()' method, skip
                pass
            else:
                # Verify that we got a dict back, and update
                if isinstance(ad, dict):
                    data.update(ad)

        return self.fixData(data)

    # Get data for Shadow Products
    def getShadowData(self):

        data = []

        if IShadowProduct.providedBy(self.context):

            for (name, adapted) in getAdapters((self.context,), IShadowProduct):
                try:
                    # Pull the 'getData()' values, and update the API data
                    ad = adapted.getData(bin=self.showBinaryData)
                except AttributeError:
                    # If there's no 'getData()' method, skip
                    pass
                else:
                    # Verify that we got a dict back, and update
                    if isinstance(ad, dict):
                        data.append(ad)

        return data

    # Get data for Sub Products
    def getSubProductData(self):

        data = []

        if ISubProduct.providedBy(self.context):

            for (name, adapted) in getAdapters((self.context,), ISubProduct):
                try:
                    # Pull the 'getData()' values, and update the API data
                    ad = adapted.getData(bin=self.showBinaryData, subproduct=False)
                except AttributeError:
                    # If there's no 'getData()' method, skip
                    pass
                else:
                    # Verify that we got a dict back, and update
                    if isinstance(ad, dict) and ad:
                        data.append(ad)

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
