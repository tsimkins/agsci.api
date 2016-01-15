from Acquisition import aq_base
from BeautifulSoup import BeautifulSoup
from DateTime import DateTime
from Products.CMFCore.utils import getToolByName
from Products.Five import BrowserView
import Missing
import json
import re
import urllib2
import urlparse
from agsci.leadimage.content.behaviors import LeadImage
from zope.publisher.interfaces import IPublishTraverse
from zope.interface import implements
import dicttoxml

# Prevent debug messages in log
dicttoxml.set_debug(False)

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

from ..utilities import toISO, encode_blob

class BaseView(BrowserView):

    implements(IPublishTraverse)

    data_format = None
    valid_data_formats = ['json', 'xml']
    default_data_format = 'xml'        

    # Check if we're recursive based on URL parameter
    # Defaults to True
    @property
    def isRecursive(self):
        v = self.request.get('recursive', 'True')
        return not (v.lower() in ('false', '0'))

    # Check if we're showing binary data
    # Defaults to True
    @property
    def showBinaryData(self):
        v = self.request.get('bin', 'True')
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
        m = self.portal_catalog.getMetadataForUID("/".join(self.context.getPhysicalPath()))
        for i in m.keys():
            if m[i] == Missing.Value:
                m[i] = ''
        return m

    def getIndexData(self):
        return self.portal_catalog.getIndexDataForUID("/".join(self.context.getPhysicalPath()))

    def getCatalogData(self):
        data = self.getMetadata()
        indexdata = self.getIndexData()
        for i in indexdata.keys():
            if not data.has_key(i):
                data[i] = indexdata[i]
        return data

    def getExcludeFields(self):
        return [
            'allowedRolesAndUsers',
            'author_name',
            'cmf_uid',
            'commentators',
            'Creator',
            'CreationDate',
            'Date',
            'EffectiveDate',
            'effectiveRange',
            'ExpirationDate',
            'getCommitteeNames',
            'getDepartmentNames',
            'getIcon',
            'getObjPositionInParent',
            'getObjSize',
            'getRawClassifications',
            'getRawCommittees',
            'getRawDepartments',
            'getRawPeople',
            'getRawSpecialties',
            'getResearchTopics',
            'getSortableName',
            'getSpecialtyNames',
            'id',
            'in_reply_to',
            'in_response_to',
            'last_comment_date',
            'meta_type',
            'ModificationDate',
            'object_provides',
            'portal_type',
            'path',
            'SearchableText',
            'sortable_title',
            'total_comments',
            'sync_uid',
        ]

    def filterData(self, data):

        excluded_fields = self.getExcludeFields()

        data['people'] = {}
        data['dates'] = {}
        
        # Human to Magento metadata mapping
        h2m = {
                'Category': 'category_level_1', 
                'Program': 'category_level_2', 
                'Topic': 'category_level_3', 
                'Subtopic': 'filters'
        }
        
                
        # First pass: Adjust data if necessary
        for i in data.keys():
        
            # Skip custom data structure keys
            if i in ('people', 'dates'):
                continue

            # Remove Excluded and empty fields
            if i in excluded_fields or not data.get(i):
                del data[i]
                continue

            v = data[i]

            if isinstance(v, DateTime):
                data[i] = toISO(data[i])
            elif i == 'listCreators':
                data['people']['creators'] = data[i]
                del data[i]
            elif i == 'listContributors':
                data['people']['contributors'] = data[i]
                del data[i]
            elif i == 'getRawRelatedItems':
                data['related_items'] = data[i]
                del data[i]
            elif i == 'getId':
                data['short_name'] = data[i]
                del data[i]
            elif i == 'review_state':
                data['workflow_state'] = data[i]
                del data[i]
            elif i == 'getRemoteUrl':
                data['remote_url'] = data[i]
                del data[i]
            elif i in h2m.keys():

                # Only create the metadata structure if our item has one of the
                # metadata values.  This contains a branch for Plone and a
                # branch for Magento, since the values are the same, but the
                # terminology is different.
                
                if not data.has_key('metadata'):            
                    data['metadata'] = {
                        'plone' : {},
                        'magento' : {},
                    }
                
                # Map Plone key to Magento key
                magento_key = h2m.get(i).lower()
                
                # Populate values and delete original key
                data['metadata']['plone'][i.lower()] = data[i]
                data['metadata']['magento'][magento_key] = data[i]
                del data[i]

            # XML type logic sees `zope.i18nmessageid.message.Message` as a list
            # and returns the type one letter at a time as a list.
            elif type(v).__name__ == 'Message':
                data[i] = unicode(v)

            # Separate block (intentionally not an 'elif') that puts all the 
            # date fields under a 'dates' structure.
            if i in ('created', 'expires', 'effective', 'modified'):
                data['dates'][i] = data[i]
                del data[i]                

        # Second pass: Ensure keys are non-camel case lowercase                
        for i in data.keys():
            formatted_key = self.format_key(i)

            if formatted_key != i:
                data[formatted_key] = data[i]
                del data[i]

        return data

    def getData(self):

        data = self.getCatalogData()

        # Object URL
        url = self.context.absolute_url()
        data['url'] = url

        # Body text
        if hasattr(self.context, 'text') and hasattr(self.context.text, 'raw'):
            data['text'] = self.context.text.raw

        # Lead Image
         
        if data.get('hasLeadImage', False):
            img_field_name = 'leadimage'
            img_field = getattr(self.context, img_field_name, None)

            (img_mimetype, img_data) = encode_blob(img_field, self.showBinaryData)

            if img_data:
                data['leadimage'] = {
                    'data' : img_data,
                    'mimetype' : img_mimetype,
                    'caption' : LeadImage(self.context).leadimage_caption,
                }

        # Related items
        # Remove acquisition wrapping, since otherwise this will also return 
        # the parent item's related items.
        aq_base_context = aq_base(self.context)
        
        if hasattr(aq_base_context, 'relatedItems'):
            data['related_items'] = [x.to_object.UID() for x in aq_base_context.relatedItems]

        return data
    
    def getFilteredData(self):
        data = self.getData()
        return self.filterData(data)        

    def getJSON(self):
        return json.dumps(self.getFilteredData(), indent=4)

    def getXML(self):
        return dicttoxml.dicttoxml(self.getFilteredData(), custom_root='item')

    def __call__(self):
        data_format = self.getDataFormat()

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

    def getStructuredData(self, schemas=[], structures={}):
        data = {}

        # Reverse lookup for all fields used in structures
        structured_fields = {}
        
        for (k,v) in structures.iteritems():
            for i in v:
                structured_fields[i] = k
                
        # Attach all custom fields from schema
        fields = []
        
        # Get additional fieldnames from schem
        for i in schemas:
            fields.extend(i.names())
            
        fields.extend(structured_fields.keys())
        
        for i in set(fields):
        
            v = getattr(self.context, i, None)
            
            # If it's a text field
            if hasattr(v, 'raw'):
                v = v.raw
            
            # Handle values, if they exist
            if v:

                # Filter out blank list items
                if isinstance(v, (list, tuple,)):
                    v = [x for x in v if x]

                # Group some fields into data structures for XML readability
                if structured_fields.has_key(i):
                    s = structured_fields.get(i)
                    if not data.has_key(s):
                        data[s] = {}
                    if i.endswith('_%s' % s):
                        data[s][i.replace('_%s' %s, '')] = v
                    elif i.startswith('%s_' % s):
                        data[s][i.replace('%s_' %s, '')] = v
                    else:
                        data[s][i] = v
                # If we're not structuring the datas
                else:
                    data[i] = v

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
    
                    data['contents'].append(api_data.getFilteredData())

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
