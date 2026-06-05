class UnfazedProcessor extends AudioWorkletProcessor {
  constructor(){
    super()
    // stateful processor initialization
    this.port.onmessage = (ev)=>{
      // receive messages from main thread
    }
  }

  process(inputs, outputs, parameters){
    // simple passthrough for now
    const input = inputs[0]
    const output = outputs[0]
    if (!input || !input.length) return true
    for (let channel = 0; channel < input.length; channel++){
      const inCh = input[channel]
      const outCh = output[channel]
      for (let i = 0; i < inCh.length; i++){
        outCh[i] = inCh[i]
      }
    }
    return true
  }
}

registerProcessor('unfazed-processor', UnfazedProcessor)
