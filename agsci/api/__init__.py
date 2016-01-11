from zope.i18nmessageid import MessageFactory
apiMessageFactory = MessageFactory('agsci.api')

def initialize(context):
    pass

# Make the import more intuitive
from api import BaseView, BaseContainerView
