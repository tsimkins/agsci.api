from .. import BaseView
from agsci.atlas.utilities import toISO
from DateTime import DateTime
from Products.CMFCore.utils import getToolByName

class PloneSiteView(BaseView):

    # Don't cache API views for the Plone site
    cache = False

    # Don't run 'expensive' adapters
    expensive = False

    # Listing of interfaces that products provide
    product_interfaces = [
                            'agsci.atlas.content.IAtlasProduct',
                            'agsci.atlas.content.behaviors.IAtlasInternalMetadata',
                            'agsci.atlas.content.behaviors.IAtlasProductCategoryMetadata',
                            'agsci.atlas.content.behaviors.IAtlasProductAttributeMetadata',
                            'agsci.atlas.content.behaviors.IAtlasEPASMetadata',
                            'agsci.atlas.content.ICounty',
                            'agsci.person.content.person.IPerson',
                        ]

    # Exclude these Types of objects from output.  Specifically, Person objects
    # will be handled separately (in the directory)
    exclude_types = ['Person', ]

    def getData(self, **kwargs):

        # Data structure to return
        data = {}

        # URL parameters
        uid = self.request.get('UID', self.request.get('uid', None))
        modified = self.getModifiedCriteria()

        # Query for object having UID, if that parameter is provided
        if uid:

            results = self.portal_catalog.searchResults({'UID' : uid})

            if results:
                o = results[0].getObject()
                data = o.restrictedTraverse('@@api').getData()

        # Otherwise, query for all products updated within X seconds, excluding
        # types configured above
        elif modified:

            # Initialize contents structure
            data["contents"] = []

            # Store 'modified' query string in response data
            data['modified'] = repr(modified)

            # Construct catalog query based on product types
            query = {
                        'object_provides' : self.product_interfaces,
                        'modified' : modified,
                        'effective' : {
                            'query' : DateTime(),
                            'range' : 'max',
                        },
                        'review_state' : ['published', 'expired', 'expiring_soon'],
                    }

            # Query catalog
            results = self.portal_catalog.searchResults(query)

            # Method to calculate sort order. For now, this puts the group
            # products first.
            def sortOrder(x):
                if x.Type.endswith(' Group'):
                    return 0
                return 1

            # Sort Results
            results = sorted(results, key=lambda x: sortOrder(x))

            # Iterate through results, skipping Person objects, and append
            # API export data to "contents" structure
            for r in results:

                # Exclude objects of a specified Type
                if r.Type in self.exclude_types:
                    continue

                o = r.getObject()

                # Traverse to the API view
                api_view = o.restrictedTraverse('@@api')

                # Append the data for this object
                data["contents"].append(api_view.data)

                # Extend contents with shadow products
                data["contents"].extend(api_view.getShadowData())

        return data
