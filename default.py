"""Settings/account frontend. Scraping is exposed through the mdmlink library."""
import os
import sys
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'lib'))
from mdmlink.ui import show
if __name__=='__main__': show()
