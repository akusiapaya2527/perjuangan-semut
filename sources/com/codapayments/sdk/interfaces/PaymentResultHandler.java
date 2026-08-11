package com.codapayments.sdk.interfaces;

import com.codapayments.sdk.model.PayResult;

/* JADX INFO: loaded from: classes.dex */
public interface PaymentResultHandler {
    void handleClose(PayResult payResult);

    void handleResult(PayResult payResult);
}
