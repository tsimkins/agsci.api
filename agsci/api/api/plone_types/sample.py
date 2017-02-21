from zope.component.interfaces import ComponentLookupError
from Products.CMFCore.utils import getToolByName
from plone.dexterity.utils import createContent, iterSchemataForType
from copy import copy
from zope import schema
from . import PloneSiteView
from datetime import datetime
import itertools
from plone.app.textfield.value import RichTextValue
from plone.namedfile.file import NamedBlobImage, NamedBlobFile
from zope.interface.interface import Method
from zope.component import getMultiAdapter
from agsci.atlas.utilities import getAllSchemaFieldsAndDescriptions

class SampleAPIView(PloneSiteView):

    placeholder = u'...'
    show_all_fields = True

    def updateValues(self, data, new_data):

        p = [dict, list, tuple, unicode, str, int, float, bool]

        def type_idx(i):
            try:
                return p.index(i.__class__)
            except ValueError:
                return 99999

        for k in new_data.keys():
            # If the current data item doesn't have an existing key, or an
            # empty/null key, replace the value with a copy of the new data.
            if not data.has_key(k) or \
               isinstance(data[k], None.__class__) or \
               not data[k] or \
               type_idx(new_data[k]) > type_idx(data[k]):
                data[k] = copy(new_data[k])

            # Otherwise, it's a valid value, combine them
            elif data.has_key(k):

                # If they're both dicts
                if isinstance(data[k], dict) and isinstance(new_data[k], dict):
                    data[k] = self.updateValues(data[k], new_data[k])

                # If they're both lists/tuples
                elif isinstance(data[k], (list, tuple)) and isinstance(new_data[k], (list, tuple)):
                    data[k] = list(data[k]) + list(new_data[k])

        return data

    def replaceValues(self, data):

        if isinstance(data, dict):
            for k in data.keys():
                data[k] = self.replaceValues(data[k])

        elif isinstance(data, (list, tuple)):
            data = [self.replaceValues(x) for x in data]

            # If data is entirely str/unicode, only present one item
            if all([isinstance(x, (str, unicode)) for x in data]):
                data = data[0:1]

            # If data is entirely list/tuple, combine contents into one list
            elif all([isinstance(x, (list, tuple)) for x in data]):
                data = [
                    self.replaceValues(list(itertools.chain(*data)))
                ]

            # If all children are dicts
            elif all([isinstance(x, dict) for x in data]):
                v = {}

                for i in data:
                    v.update(i)

                data = [v,]


        elif isinstance(data, (str, unicode)):
            data = self.placeholder

        elif isinstance(data, (int, float)):
            data = self.placeholder

        elif isinstance(data, None.__class__):
            data = self.placeholder

        return data

    def getDefaultForFieldType(self, field):

        # Field Class
        field_klass = field.__class__.__name__

        # Return nothing for methods
        if field_klass in ['Method',]:
            return None

        # Define dummy fields

        rich_text = RichTextValue(raw='<p>%s</p>' % self.placeholder,
                                  mimeType=u'text/html',
                                  outputMimeType='text/x-html-safe')

        named_blob_file = NamedBlobFile(filename=u'sample.pdf',
                                        contentType='application/pdf')

        named_blob_file.data = self.placeholder.encode('utf-8')

        named_blob_image = NamedBlobImage(filename=u'sample.png',
                                        contentType='image/png')

        named_blob_image.data = self.placeholder.encode('utf-8')

        # Simple field defaults

        defaults = {
            'Int' : 10,
            'Text' : "\n".join(3*[self.placeholder]),
            'List' : 3*[self.placeholder],
            'TextLine' : self.placeholder,
            'Bool' : True,
            'Datetime' : datetime.now(),
            'RichText' : rich_text,
            'NamedBlobFile' : named_blob_file,
            'NamedBlobImage' : named_blob_image,
            'Choice' : self.placeholder,
        }

        # If a default, return that.  Otherwise, return the placeholder.
        return defaults.get(field_klass, self.placeholder)



    def getData(self):

        # Not recursive, no binaries
        self.request.form['recursive'] = '0'
        self.request.form['bin'] = '0'

        # Data structure to return
        sample_data = {}

        # Get portal_types object
        portal_types = getToolByName(self.context, "portal_types")

        # Iterate through the portal types
        for pt in portal_types.listTypeInfo():

            # Get the base schema
            schema = getattr(pt, 'schema', None)

            # if we have a base schema, and it's an agsci.atlas content
            if schema and any([schema.startswith(x) for x in ['agsci.atlas', 'agsci.person']]):
                portal_type = pt.getId()

                kwargs = {}

                for s in iterSchemataForType(portal_type):

                    for (name, field) in getAllSchemaFieldsAndDescriptions(s):
                        if not isinstance(field, Method):
                            kwargs[name] = self.getDefaultForFieldType(field)

                # Create a dummy object with default values
                o = createContent(portal_type, **kwargs)

                # Set id
                o.id = 'X_%s_X' % portal_type

                # Run the API view against it
                try:
                    api_view = getMultiAdapter((o, self.request), name='api')

                except ComponentLookupError:
                    pass

                else:

                    if api_view.isProduct():
                        # Update sample data with API output
                        sample_data = self.updateValues(sample_data, api_view.getData())

                        # Update sample data with shadow API output
                        for i in api_view.getShadowData():
                            sample_data.update(i)

        # Data structure to return
        data = {}

        # Replace strings with placeholders
        sample_data = self.replaceValues(sample_data)

        # Add a dummy "contents" field
        sample_data['contents'] = [self.placeholder]


        # Initialize contents structure
        data['contents'] = [sample_data,]

        # Store 'modified' query string in response data
        data['modified'] = self.placeholder

        return data
