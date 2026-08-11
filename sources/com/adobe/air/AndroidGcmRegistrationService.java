package com.adobe.air;

import android.app.IntentService;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.ResultReceiver;
import android.preference.PreferenceManager;
import android.support.v4.widget.ExploreByTouchHelper;
import android.util.Log;
import com.amazonaws.AmazonClientException;
import com.amazonaws.AmazonServiceException;
import com.amazonaws.auth.BasicAWSCredentials;
import com.amazonaws.regions.Region;
import com.amazonaws.regions.Regions;
import com.amazonaws.services.sns.AmazonSNS;
import com.amazonaws.services.sns.AmazonSNSClient;
import com.amazonaws.services.sns.model.CreatePlatformEndpointRequest;
import com.amazonaws.services.sns.model.CreatePlatformEndpointResult;
import com.amazonaws.services.sns.model.InternalErrorException;
import com.amazonaws.services.sns.model.InvalidParameterException;
import com.amazonaws.services.sns.model.SetEndpointAttributesRequest;
import com.google.android.gms.common.GooglePlayServicesUtil;
import com.google.android.gms.gcm.GoogleCloudMessaging;
import java.util.HashMap;

/* JADX INFO: loaded from: classes.dex */
public class AndroidGcmRegistrationService extends IntentService {
    private static final String CUSTOM_USER_DATA = "CustomUserData";
    private static final String ENABLED = "Enabled";
    private static final String ENABLE_LOGGING = "enableLogging";
    private static final int MAX_RETRIES = 10;
    private static final String PROPERTY_APP_VERSION = "appVersion";
    private static final String PROPERTY_ENDPOINT_ARN = "endpointArn";
    private static final String RATE_LIMIT = "rateLimit";
    private static final int RETRY_TIME = 300000;
    private static final String TAG = "AndroidGcmRegistrationService";
    private static final String TEST_ACCESS_KEY = "";
    private static final String TEST_APPLICATION_ARN = "arn:aws:sns:us-west-2:413177889857:app/GCM/airruntimetestapp";
    private static final String TEST_ENV = "testEnv";
    private static final String TEST_SECRET_KEY = "";
    private static final String TEST_SENDER_ID = "1078258869814";
    private static final String TOKEN = "Token";
    private AmazonSNS mClient;
    private boolean mEnableLogging;
    private String mEndpointArn;
    private GoogleCloudMessaging mGcm;
    private String mRegId;
    private ResultReceiver mResultReceiver;
    private int mRetryCount;
    private boolean mTestEnv;
    private static String SENDER_ID = "233437466354";
    private static String APPLICATION_ARN = "arn:aws:sns:us-west-2:502492504188:app/GCM/AdobeAIRGCM";
    private static String ACCESS_KEY = "";
    private static String SECRET_KEY = "";

    public AndroidGcmRegistrationService() {
        super(TAG);
        this.mRetryCount = 0;
        this.mRegId = null;
        this.mEndpointArn = null;
        this.mClient = null;
        this.mGcm = null;
        this.mResultReceiver = null;
        this.mEnableLogging = false;
        this.mTestEnv = false;
    }

    @Override // android.app.IntentService
    protected void onHandleIntent(Intent intent) {
        this.mResultReceiver = (ResultReceiver) intent.getParcelableExtra(AdobeAIRMainActivity.RESULT_RECEIVER);
        registerForNotifications();
    }

    private void registerForNotifications() {
        if (!isAppRegistered() && checkPlayServices()) {
            configureTestEnv();
            registerInBackground(0);
        }
    }

    private boolean checkPlayServices() {
        int iIsGooglePlayServicesAvailable = GooglePlayServicesUtil.isGooglePlayServicesAvailable(this);
        if (iIsGooglePlayServicesAvailable == 0) {
            return true;
        }
        if (GooglePlayServicesUtil.isUserRecoverableError(iIsGooglePlayServicesAvailable) && this.mResultReceiver != null) {
            this.mResultReceiver.send(iIsGooglePlayServicesAvailable, null);
        }
        return false;
    }

    private boolean isAppRegistered() {
        int i = PreferenceManager.getDefaultSharedPreferences(getApplicationContext()).getInt(PROPERTY_APP_VERSION, ExploreByTouchHelper.INVALID_ID);
        return i != Integer.MIN_VALUE && i == getAppVersion();
    }

    private void configureTestEnv() {
        try {
            Bundle bundle = getPackageManager().getServiceInfo(new ComponentName(this, getClass()), 128).metaData;
            if (bundle != null) {
                this.mEnableLogging = bundle.getBoolean(ENABLE_LOGGING);
                this.mTestEnv = bundle.getBoolean(TEST_ENV);
                if (this.mTestEnv) {
                    SENDER_ID = TEST_SENDER_ID;
                    APPLICATION_ARN = TEST_APPLICATION_ARN;
                    ACCESS_KEY = "";
                    SECRET_KEY = "";
                    int i = bundle.getInt(RATE_LIMIT, ExploreByTouchHelper.INVALID_ID);
                    if (i != Integer.MIN_VALUE) {
                        AdobeAIRMainActivity.RATE_LIMIT = i;
                    }
                }
            }
        } catch (PackageManager.NameNotFoundException e) {
        }
    }

    /* JADX INFO: Access modifiers changed from: private */
    public void registerInBackground(int i) {
        if (this.mRetryCount < 10) {
            if (i != 0) {
                this.mRetryCount++;
            }
            if (this.mGcm == null) {
                this.mGcm = GoogleCloudMessaging.getInstance(this);
            }
            new AsyncTaskRunner().execute(Integer.valueOf(i));
        }
    }

    private class AsyncTaskRunner extends AsyncTask<Integer, Void, Void> {
        private AsyncTaskRunner() {
        }

        /* JADX INFO: Access modifiers changed from: protected */
        @Override // android.os.AsyncTask
        public Void doInBackground(Integer... numArr) {
            try {
                Thread.sleep(numArr[0].intValue());
                AndroidGcmRegistrationService.this.mRegId = AndroidGcmRegistrationService.this.mGcm.register(AndroidGcmRegistrationService.SENDER_ID);
                if (AndroidGcmRegistrationService.this.mRegId == null) {
                    AndroidGcmRegistrationService.this.registerInBackground(AndroidGcmRegistrationService.RETRY_TIME);
                } else {
                    AndroidGcmRegistrationService.this.sendRegistrationIdToAws();
                }
                return null;
            } catch (Exception e) {
                AndroidGcmRegistrationService.this.registerInBackground(AndroidGcmRegistrationService.RETRY_TIME);
                return null;
            }
        }
    }

    private int getAppVersion() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
        } catch (PackageManager.NameNotFoundException e) {
            return 0;
        }
    }

    /* JADX INFO: Access modifiers changed from: private */
    public void sendRegistrationIdToAws() {
        try {
            BasicAWSCredentials basicAWSCredentials = new BasicAWSCredentials(ACCESS_KEY, SECRET_KEY);
            Region region = Region.getRegion(Regions.US_WEST_2);
            this.mClient = new AmazonSNSClient(basicAWSCredentials);
            this.mClient.setRegion(region);
            try {
                try {
                    CreatePlatformEndpointRequest createPlatformEndpointRequest = new CreatePlatformEndpointRequest();
                    createPlatformEndpointRequest.setPlatformApplicationArn(APPLICATION_ARN);
                    createPlatformEndpointRequest.setToken(this.mRegId);
                    createPlatformEndpointRequest.setCustomUserData(getCustomData());
                    CreatePlatformEndpointResult createPlatformEndpointResultCreatePlatformEndpoint = this.mClient.createPlatformEndpoint(createPlatformEndpointRequest);
                    if (createPlatformEndpointResultCreatePlatformEndpoint != null && createPlatformEndpointResultCreatePlatformEndpoint.getEndpointArn() != null) {
                        this.mEndpointArn = createPlatformEndpointResultCreatePlatformEndpoint.getEndpointArn();
                        if (this.mEnableLogging) {
                            Log.i(TAG, "Creation EndpointArn = " + this.mEndpointArn);
                        }
                        updateSharedPref();
                    }
                } catch (InvalidParameterException e) {
                    updateEndpointAttributes();
                }
            } catch (InternalErrorException e2) {
                registerInBackground(RETRY_TIME);
            } catch (AmazonClientException e3) {
            } catch (AmazonServiceException e4) {
            }
        } catch (Exception e5) {
        }
    }

    private void updateEndpointAttributes() {
        try {
            SetEndpointAttributesRequest setEndpointAttributesRequest = new SetEndpointAttributesRequest();
            if (this.mEndpointArn == null) {
                this.mEndpointArn = PreferenceManager.getDefaultSharedPreferences(getApplicationContext()).getString(PROPERTY_ENDPOINT_ARN, "");
                if (this.mEnableLogging) {
                    Log.i(TAG, "Update EndpointArn = " + this.mEndpointArn);
                }
            }
            setEndpointAttributesRequest.setEndpointArn(this.mEndpointArn);
            HashMap map = new HashMap();
            map.put(CUSTOM_USER_DATA, getCustomData());
            map.put(ENABLED, "true");
            map.put(TOKEN, this.mRegId);
            setEndpointAttributesRequest.setAttributes(map);
            this.mClient.setEndpointAttributes(setEndpointAttributesRequest);
            updateSharedPref();
        } catch (AmazonClientException e) {
        } catch (AmazonServiceException e2) {
        }
    }

    /* JADX WARN: Removed duplicated region for block: B:23:0x010c  */
    /*
        Code decompiled incorrectly, please refer to instructions dump.
        To view partially-correct add '--show-bad-code' argument
    */
    private java.lang.String getCustomData() {
        /*
            Method dump skipped, instruction units count: 270
            To view this dump add '--comments-level debug' option
        */
        throw new UnsupportedOperationException("Method not decompiled: com.adobe.air.AndroidGcmRegistrationService.getCustomData():java.lang.String");
    }

    private void updateSharedPref() {
        SharedPreferences defaultSharedPreferences = PreferenceManager.getDefaultSharedPreferences(getApplicationContext());
        int appVersion = getAppVersion();
        SharedPreferences.Editor editorEdit = defaultSharedPreferences.edit();
        editorEdit.putInt(PROPERTY_APP_VERSION, appVersion);
        editorEdit.putString(PROPERTY_ENDPOINT_ARN, this.mEndpointArn);
        editorEdit.commit();
    }
}
