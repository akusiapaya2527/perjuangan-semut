package com.boyaa.antwarsId;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import com.boyaa.iap.googlePlayV3.GoogleCheckoutHelper;

/* JADX INFO: loaded from: classes.dex */
public class GooglePlayPaymentActivity extends Activity {
    private String purchaseObject;

    public static void main(String[] args) {
    }

    @Override // android.app.Activity
    protected void onCreate(Bundle savedInstanceState) {
        AntExtension.log("GooglePlayPaymentActivity create!");
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        Bundle bundle = intent.getExtras();
        this.purchaseObject = bundle.getString("google");
        startPurchase();
    }

    private void startPurchase() {
        AntExtension.log("GooglePlayPaymentActivity startPurchase!");
        GoogleCheckoutHelper.getInstance(this).startPurchase(this.purchaseObject);
    }

    @Override // android.app.Activity
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        AntExtension.log("[onActivityResult] requestCode:" + requestCode + " resultCode:" + resultCode);
        GoogleCheckoutHelper.getInstance(this).onActivityResult(requestCode, resultCode, data);
        GoogleCheckoutHelper.getInstance(this).onDestroy();
        finish();
    }
}
