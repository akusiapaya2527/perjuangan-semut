package com.freshplanet.ane.AirFacebook;

/* JADX INFO: loaded from: classes.dex */
public class AirFacebookError {
    public static final String NOT_INITIALIZED = "not_initialized";

    public static final String makeJsonError(Exception exc) {
        return makeJsonError(exc.getMessage());
    }

    public static final String makeJsonError(String str) {
        return "{ \"error\" : \"" + str + "\"}";
    }
}
