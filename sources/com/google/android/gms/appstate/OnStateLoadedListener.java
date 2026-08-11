package com.google.android.gms.appstate;

/* JADX INFO: loaded from: classes.dex */
public interface OnStateLoadedListener {
    void onStateConflict(int i, String str, byte[] bArr, byte[] bArr2);

    void onStateLoaded(int i, int i2, byte[] bArr);
}
