package com.google.android.gms.auth;

import android.content.Intent;

/* JADX INFO: loaded from: classes.dex */
public class UserRecoverableAuthException extends GoogleAuthException {
    private final Intent mIntent;

    public UserRecoverableAuthException(String msg, Intent intent) {
        super(msg);
        this.mIntent = intent;
    }

    public Intent getIntent() {
        return new Intent(this.mIntent);
    }
}
