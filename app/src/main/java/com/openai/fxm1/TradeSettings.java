package com.openai.fxm1;

import android.app.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import java.math.BigDecimal;
import java.util.*;
import org.json.*;

/** Selected profile is distinct from broker identity. All order checks remain server-side. */
public final class TradeSettings {
    private TradeSettings(){}
    public static String autoTitle(){return "AUTO TRADING  •  "+EventClient.accountMode();}
    public static double parseVolume(String input,JSONObject instrument){
        String value=input==null?"":input.trim().replace(',','.');
        if(!value.matches("[0-9]+(?:\\.[0-9]+)?"))throw new IllegalArgumentException("Введите положительный объём в лотах, например 0.05");
        BigDecimal volume=new BigDecimal(value);
        if(volume.signum()<=0||!Double.isFinite(volume.doubleValue())||volume.doubleValue()>1000)
            throw new IllegalArgumentException("Объём должен быть больше нуля и не выше 1000 лотов");
        if(instrument!=null){
            double min=instrument.optDouble("volume_min",0),max=instrument.optDouble("volume_max",1000),step=instrument.optDouble("volume_step",0);
            if(volume.doubleValue()<min-1e-10||volume.doubleValue()>max+1e-10)throw new IllegalArgumentException("Допустимый объём MT5: "+min+" … "+max);
            if(Double.isFinite(step)&&step>0&&volume.remainder(BigDecimal.valueOf(step)).abs().doubleValue()>1e-9)
                throw new IllegalArgumentException("Объём должен соответствовать шагу MT5: "+step);
        }
        return volume.doubleValue();
    }
    private static String format(double x){return new BigDecimal(Double.toString(x)).setScale(Math.max(2,new BigDecimal(Double.toString(x)).stripTrailingZeros().scale())).toPlainString();}
    public static void bindLot(Activity activity,Spinner spinner,Runnable changed){
        ArrayList<String> labels=new ArrayList<>(Arrays.asList("0.01","0.05","0.10","0.50","1.00"));
        String saved=EventClient.prefs().getString("ec_lot_cap","0.01");
        try{saved=format(parseVolume(saved,null));}catch(IllegalArgumentException e){labels.add(saved+" (исправьте)");}
        int selected=labels.indexOf(saved);if(selected<0){labels.add(saved);selected=labels.size()-1;}
        labels.add("Вручную…");
        ArrayAdapter<String> adapter=new ArrayAdapter<String>(activity,android.R.layout.simple_spinner_item,labels){
            @Override public View getView(int pos,View view,ViewGroup parent){TextView t=(TextView)super.getView(pos,view,parent);t.setTextColor(0xffeeeeff);t.setTextSize(19);return t;}
            @Override public View getDropDownView(int pos,View view,ViewGroup parent){TextView t=(TextView)super.getDropDownView(pos,view,parent);t.setTextColor(0xffeeeeff);t.setBackgroundColor(0xff211831);t.setPadding(20,20,20,20);return t;}
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setOnItemSelectedListener(null);spinner.setAdapter(adapter);spinner.setSelection(selected);
        spinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onNothingSelected(AdapterView<?> p){}
            public void onItemSelected(AdapterView<?> parent,View v,int pos,long id){
                String chosen=labels.get(pos);
                if(chosen.equals("Вручную…")){manual(activity,spinner,changed);return;}
                try{
                    double lot=parseVolume(chosen,EventClient.state().optJSONObject("instrument"));
                    double old=parseVolume(EventClient.prefs().getString("ec_lot_cap","0.01"),null);
                    if(Math.abs(old-lot)<1e-10)return;
                    EventClient.prefs().edit().putString("ec_lot_cap",format(lot)).apply();changed.run();
                }catch(IllegalArgumentException e){Toast.makeText(activity,e.getMessage(),Toast.LENGTH_LONG).show();}
            }
        });
    }
    private static void manual(Activity a,Spinner spinner,Runnable changed){
        EditText input=new EditText(a);input.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL);
        input.setText(EventClient.prefs().getString("ec_lot_cap","0.01"));input.selectAll();
        AlertDialog dialog=new AlertDialog.Builder(a).setTitle("Объём позиции, лот").setMessage("Выбранный объём проверяется по риску, марже и ограничениям MT5. Он не уменьшается молча.")
            .setView(input).setNegativeButton("ОТМЕНА",(d,w)->bindLot(a,spinner,changed)).setPositiveButton("СОХРАНИТЬ",null).create();
        dialog.setOnCancelListener(d->bindLot(a,spinner,changed));
        dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{try{
            double lot=parseVolume(input.getText().toString(),EventClient.state().optJSONObject("instrument"));
            EventClient.prefs().edit().putString("ec_lot_cap",format(lot)).apply();bindLot(a,spinner,changed);changed.run();dialog.dismiss();
        }catch(IllegalArgumentException e){input.setError(e.getMessage());}}));dialog.show();
    }
}
