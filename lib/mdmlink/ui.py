import json
import time
import xbmc
import xbmcaddon
import xbmcgui
from .alldebrid import AllDebrid
from .errors import PlaybackError, Cancelled
from .api import status

def authorise(addon):
    progress=None
    try:
        client=AllDebrid(addon)
        data=client.request('v4.1/pin/get',authenticated=False)
        pin,check=data.get('pin'),data.get('check')
        if not isinstance(pin,str) or not pin.isalnum() or not isinstance(check,str) or not check:
            raise PlaybackError('AllDebrid returned invalid PIN details.')
        expires=data.get('expires_in',600)
        expires=min(expires,600) if type(expires) is int and expires>0 else 600
        deadline=time.monotonic()+expires
        progress=xbmcgui.DialogProgress(); progress.create('MDM Link / AllDebrid','Visit https://alldebrid.com/pin/\nEnter PIN: '+pin+'\nKeep this dialog open.')
        monitor=xbmc.Monitor()
        while time.monotonic()<deadline:
            client.wait(progress,monitor)
            data=client.request('v4/pin/check',{'pin':pin,'check':check},authenticated=False)
            if data.get('activated') is True and isinstance(data.get('apikey'),str) and data['apikey']:
                addon.setSetting('alldebrid_api_key',data['apikey']); addon.setSetting('alldebrid_enabled','true')
                addon.setSetting('flix_account_imported','true')
                xbmcgui.Dialog().notification('MDM Link','AllDebrid authorised.',xbmcgui.NOTIFICATION_INFO,3000)
                return
        raise PlaybackError('AllDebrid PIN expired. Try again.')
    except Cancelled: pass
    except PlaybackError as error: xbmcgui.Dialog().ok('MDM Link',str(error))
    finally:
        if progress: progress.close()

def check_account(addon):
    try:
        client=AllDebrid(addon); user=client.user()
        xbmcgui.Dialog().textviewer('MDM Link / AllDebrid','Authorisation: valid\nEnabled: {}\nSubscription: {}'.format(
            'yes' if client.enabled else 'no','active' if user.get('isPremium') is True else 'inactive / limited'))
    except PlaybackError as error: xbmcgui.Dialog().ok('MDM Link',str(error))

def disconnect(addon):
    if xbmcgui.Dialog().yesno('MDM Link','Remove Link AllDebrid authorisation locally? Existing Flix/CocoScrapers authorisation stays separate.'):
        addon.setSetting('alldebrid_api_key',''); addon.setSetting('alldebrid_enabled','false')
        addon.setSetting('flix_account_imported','true')
        xbmcgui.Dialog().notification('MDM Link','AllDebrid disconnected locally.',xbmcgui.NOTIFICATION_INFO,3000)

def show():
    addon=xbmcaddon.Addon('script.mdm.link')
    choice=xbmcgui.Dialog().select('MDM Link',['Provider / mode settings','Authorise AllDebrid','Check AllDebrid account','Disconnect AllDebrid','Diagnostics'])
    if choice==0: addon.openSettings()
    elif choice==1: authorise(addon)
    elif choice==2: check_account(addon)
    elif choice==3: disconnect(addon)
    elif choice==4: xbmcgui.Dialog().textviewer('MDM Link diagnostics',json.dumps(status(addon),indent=2))
