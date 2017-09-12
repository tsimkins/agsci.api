from Products.CMFCore.WorkflowCore import WorkflowException
from Products.CMFCore.utils import getToolByName
from collective.z3cform.datagridfield.row import DictRow
from copy import copy
from datetime import datetime
from plone.app.textfield.value import RichTextValue
from plone.dexterity.utils import createContentInContainer, iterSchemataForType
from plone.namedfile.file import NamedBlobImage, NamedBlobFile
from zLOG import LOG, INFO
from zope import schema
from zope.component import getMultiAdapter, getUtility
from zope.component.hooks import getSite
from zope.component.interfaces import ComponentLookupError
from zope.interface.interface import Method
from zope.schema.interfaces import IVocabularyFactory
from zope.schema.vocabulary import SimpleVocabulary

import itertools
import transaction

from agsci.atlas.utilities import execute_under_special_role
from agsci.atlas.utilities import getAllSchemaFieldsAndDescriptions

from . import PloneSiteView

class SampleAPIView(PloneSiteView):

    placeholder = u'...'
    show_all_fields = True
    debug = False
    pretty_xml = True

    # Merge values with existing values, preferring more complex data types
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
               type_idx(new_data[k]) < type_idx(data[k]):
                data[k] = copy(new_data[k])

            # Otherwise, it's a valid value, combine them
            elif data.has_key(k):

                # If they're both dicts
                if isinstance(data[k], dict) and isinstance(new_data[k], dict):
                    data[k] = self.updateValues(data[k], new_data[k])

                # If they're both lists/tuples
                elif isinstance(data[k], (list, tuple)) and isinstance(new_data[k], (list, tuple)):
                    data[k] = list(data[k]) + list(new_data[k])

                    # Unique values if they're all strings
                    if all([isinstance(x, (str, unicode)) for x in data[k]]):
                        data[k] = list(set(data[k]))

        return data

    # Replace values with placeholders
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

    # Based on the field definition provide a default value
    def getDefaultForFieldType(self, field):

        # default string
        default_value = self.placeholder

        # Field Class
        field_klass = field.__class__.__name__

        # Handle different value_type attributes of the field.
        value_type = getattr(field, 'value_type', None)

        if value_type:
            # If we're a data grid field
            if isinstance(value_type, DictRow):
                kwargs = {}

                s = getattr(value_type, 'schema', None)

                if s:
                    for (_name, _field) in getAllSchemaFieldsAndDescriptions(s):
                        if not isinstance(field, Method):
                            kwargs[_name] = self.getDefaultForFieldType(_field)

                return [kwargs,]
            elif isinstance(value_type, (schema.TextLine,)):
                pass
            elif isinstance(value_type, (schema.Choice,)):
                vocabulary_name = getattr(value_type, 'vocabularyName', None)
                vocabulary = getattr(value_type, 'vocabulary', None)

                if vocabulary_name:
                    vocabulary_factory = getUtility(IVocabularyFactory, vocabulary_name)
                    vocabulary = vocabulary_factory(self.context)

                if vocabulary:
                    if isinstance(vocabulary, SimpleVocabulary):
                        try:
                            default_value = vocabulary.by_value.keys()[0]
                        except:
                            pass
                    else:
                        pass

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
            'List' : [default_value,],
            'Tuple' : (default_value,),
            'TextLine' : default_value,
            'Bool' : True,
            'Datetime' : datetime.now(),
            'RichText' : rich_text,
            'NamedBlobFile' : named_blob_file,
            'NamedBlobImage' : named_blob_image,
            'Choice' : default_value,
        }

        # If a default, return that.  Otherwise, return the placeholder.
        return defaults.get(field_klass, self.placeholder)

    def createObjectOfType(self, root, pt):

        # Set return list
        rv = []

        # Get the it of the portal_type
        portal_type = pt.getId()

        # Check if type is allowed
        allowed_content_types = [x.getId() for x in root.getAllowedTypes()]

        # Override for root folder (only structures)
        if root.portal_type == 'Folder':
            allowed_content_types = ['atlas_category_level_1', 'atlas_county',
                                     'state_extension_team', 'directory']

        if portal_type in allowed_content_types:

            kwargs = {}

            for s in iterSchemataForType(portal_type):

                for (name, field) in getAllSchemaFieldsAndDescriptions(s):
                    if not isinstance(field, Method):
                        kwargs[name] = self.getDefaultForFieldType(field)

            # Set the id
            kwargs['id'] = 'X_%s_X' % portal_type

            # Debug output
            if self.debug:
                msg = "Creating %s in %s" % (portal_type, root.portal_type)
                LOG('API Sample Generator', INFO, msg)

            # Create a dummy object with default values
            try:
                o = createContentInContainer(root, portal_type, **kwargs)
            except WorkflowException:
                # For some reason, we're getting a workflow exception on article videos?
                return rv

            # Append to return list
            rv.append(o)

            # Get the allowed object types
            _allowed_content_types = pt.allowed_content_types

            # Override for category level 2 (no products!)
            if portal_type == 'atlas_category_level_2':
                _allowed_content_types = ['atlas_category_level_3']

            # Create sub-objects
            for _pt_id in _allowed_content_types:

                # Prevent recursion... Don't create a type inside itself.
                if _pt_id == portal_type:
                    continue
                try:
                    _o = self.createObjectOfType(o, self.portal_types[_pt_id])
                    rv.extend(_o)
                except RuntimeError:
                    # Skip if something bombs out from recursive calls
                    pass
                except TypeError:
                    # Skip if something bombs out with a TypeError
                    pass

            return rv

    # Get portal_types object
    @property
    def portal_types(self):
        return getToolByName(self.context, "portal_types")

    def getData(self, **kwargs):

        # Since the .getSampleData() method has the potential to be a little wonky,
        # catch and pass along exceptions.  Then abort the transaction so an
        # exception won't cause any actual changes.
        if self.debug:

            data = execute_under_special_role(['Contributor', 'Reader', 'Editor', 'Member'], self.getSampleData)

        else:

            try:
                data = execute_under_special_role(['Contributor', 'Reader', 'Editor', 'Member'], self.getSampleData)
            except Exception, e:
                data = {
                        'exception' : e.__class__.__name__,
                        'message' : e.message,
                    }

        # Abort the transaction so nothing actually gets created.
        transaction.abort()

        return data

    # Create a temporary structure and get merged API output of that structure.
    def getSampleData(self):

        # List of objects
        objects = []

        # Data structure to return
        sample_data = {}

        # Create root folder to hold temporary structure
        site = getSite()
        root = createContentInContainer(site, 'Folder', title='Root Folder')

        # Iterate through the portal types, and create one of each type, plus all subtypes
        for pt in self.portal_types.listTypeInfo():

            # Get the base schema
            schema = getattr(pt, 'schema', None)

            # if we have a base schema, and it's an agsci.atlas content
            if schema and any([schema.startswith(x) for x in ['agsci.']]):
                rv = self.createObjectOfType(root, pt)

                if rv:
                    objects.extend(rv)

        # Iterate through the objects created, and run the API against them.
        for o in objects:

            # Run the API view against it
            try:
                api_view = getMultiAdapter((o, self.request), name='api')

            except ComponentLookupError:
                pass

            else:
                # Don't scrub empty fields.
                api_view.show_all_fields = self.show_all_fields

                # Include only products
                if api_view.isProduct():

                    # Update sample data with API output
                    sample_data = self.updateValues(sample_data, api_view.getData())

                    # Update sample data with shadow API output
                    for i in api_view.getShadowData():
                        sample_data = self.updateValues(sample_data, i)

        # Data structure to return
        data = {}

        # Replace strings with placeholders
        sample_data = self.replaceValues(sample_data)

        # Fix the data
        sample_data = self.fixData(sample_data)

        # Add a dummy "description" field
        sample_data['description'] = self.placeholder

        # Add a dummy "contents" field
        sample_data['contents'] = [self.placeholder]

        # Initialize contents structure
        data['contents'] = [sample_data,]

        # Store 'modified' query string in response data
        data['modified'] = self.placeholder

        return data
