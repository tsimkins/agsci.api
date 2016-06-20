from .. import BaseView
from agsci.api.utilities import toISO
from Products.CMFCore.utils import getToolByName
from DateTime import DateTime

class PloneSiteView(BaseView):

    # Default window for listing updated items
    default_updated = 3600

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
        updated = self.request.get('updated', None)

        # Query for object having UID, if that parameter is provided
        if uid:

            results = self.portal_catalog.searchResults({'UID' : uid})

            if results:
                o = results[0].getObject()
                data = o.restrictedTraverse('@@api').getData()

        # Otherwise, query for all products updated within X seconds, excluding
        # types configured above
        elif updated:

            # Initialize contents structure
            data["contents"] = []

            # Cast 'updated' parameter to an integer, using the default above
            # if this fails
            try:
                updated = int(updated)
            except ValueError:
                updated = self.default_updated

            # Calculate minimum last modified date based on URL parameter
            modified = DateTime() - (updated/86400.0)

            # Store 'updated' and 'modified' values in response data
            data['updated'] = updated
            data['modified'] = toISO(modified)

            # Construct catalog query based on product types 
            query = {
                        'object_provides' : self.product_interfaces,
                        'modified' : {'range' : 'min', 'query' : modified}
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