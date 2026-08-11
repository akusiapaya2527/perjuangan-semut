package com.freshplanet.ane.AirFacebook.functions;

import com.adobe.fre.FREContext;
import com.adobe.fre.FREObject;
import com.freshplanet.ane.AirFacebook.AirFacebookExtension;

/* JADX INFO: loaded from: classes.dex */
public class InitFunction extends BaseFunction {
    @Override // com.freshplanet.ane.AirFacebook.functions.BaseFunction, com.adobe.fre.FREFunction
    public FREObject call(FREContext fREContext, FREObject[] fREObjectArr) {
        super.call(fREContext, fREObjectArr);
        String stringFromFREObject = getStringFromFREObject(fREObjectArr[0]);
        AirFacebookExtension.log("Initializing with application ID " + stringFromFREObject);
        AirFacebookExtension.context.init(stringFromFREObject);
        return null;
    }
}
