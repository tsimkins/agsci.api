from .. import BaseView
from agsci.atlas.utilities import toISO
from Products.CMFCore.utils import getToolByName

class PloneSiteView(BaseView):

    # Listing of interfaces that products provide
    product_interfaces = ['agsci.atlas.content.behaviors.IAtlasMetadata',]
    
    # Exclude these Types of objects from output.  Specifically, Person objects
    # will be handled separately (in the directory)
    exclude_types = ['Person', ]

    def getData(self):

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
                    }

            # Query catalog
            results = self.portal_catalog.searchResults(query)

            # Iterate through results, skipping Person objects, and append 
            # API export data to "contents" structure
            for r in results:

                # Exclude objects of a specified Type
                if r.Type in self.exclude_types:
                    continue

                o = r.getObject()

                data["contents"].append(o.restrictedTraverse('@@api').getData())

        return data
