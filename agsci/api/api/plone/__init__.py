from .. import BaseView
from Products.CMFCore.utils import getToolByName

class PloneSiteView(BaseView):

    def getData(self):

        uid = self.request.get('UID', self.request.get('uid', None))
        
        if uid:
            portal_catalog = getToolByName(self.context, 'portal_catalog')
            results = portal_catalog.searchResults({'UID' : uid})
            if results:
                o = results[0].getObject()
                return o.restrictedTraverse('@@api').getData()

        return {}
